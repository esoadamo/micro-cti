import itertools
import re
import time
import asyncio
from math import floor, ceil
from functools import partial
from datetime import datetime, timedelta, timezone
from functools import reduce
from statistics import mean
from typing import List, Tuple, Union, Iterable, Optional

import fuzzywuzzy.process
import fuzzywuzzy.fuzz
from lark import Lark, Transformer, v_args, ParseError
from prisma.models import Post

from db import get_db

SEARCH_GRAMMAR = r"""
?start: expr

?expr: expr term   -> or_expr
     | expr_explicit
     
?expr_explicit: expr OR term   -> or_expr
     | term

?term: term AND factor -> and_expr
     | factor

?factor: quoted_phrase
       | multi_word
       | "(" expr ")"

multi_word: WORD+

quoted_phrase: ESCAPED_STRING

AND: "AND"
OR: "OR"

WORD: /[^\s()]+/

%import common.ESCAPED_STRING
%import common.WS
%ignore WS
"""


parser = Lark(SEARCH_GRAMMAR, start='start', parser='lalr')


@v_args(inline=True)
class QueryTransformer(Transformer):
    def __init__(self):
        super().__init__()

    def or_expr(self, *args):
        # Flatten nested OR expressions
        or_terms = []
        for arg in args:
            if isinstance(arg, dict) and "OR" in arg:
                or_terms.extend(arg["OR"])
            else:
                or_terms.append(arg)
        return {"OR": or_terms}

    def and_expr(self, *args):
        # Flatten nested AND expressions
        and_terms = []
        for arg in args:
            if isinstance(arg, dict) and "AND" in arg:
                and_terms.extend(arg["AND"])
            else:
                and_terms.append(arg)
        return {"AND": and_terms}

    def quoted_phrase(self, phrase):
        # Remove surrounding quotes and convert to lowercase
        clean_phrase = phrase[1:-1].lower()
        return {"exact": clean_phrase}

    def multi_word(self, *words):
        # Join multiple words into a single string
        return {"term": " ".join(words).lower()}

    def expr(self, expr):
        return expr

    def term(self, term):
        return term

    def factor(self, factor):
        return factor

    def start(self, expr):
        return expr


def parse_query(query):
    try:
        tree = parser.parse(query)
    except Exception as e:
        raise ParseError(f"Invalid query syntax: {e}")
    transformer = QueryTransformer()
    return transformer.transform(tree)


def evaluate_ast(ast: Union[list, dict], post: Post, strict: bool = False) -> Optional[float]:
    if isinstance(ast, dict):
        if "OR" in ast:
            # OR score is counted as sum of the children
            child_scores = list(filter(lambda x: x is not None, [evaluate_ast(child, post) for child in ast["OR"]]))
            return max(child_scores) if child_scores else 1
        if "AND" in ast:
            # AND score is counted as product of the children
            child_scores = list(filter(lambda x: x is not None, [evaluate_ast(child, post) for child in ast["AND"]]))
            return min(child_scores) if child_scores else 1
        if "exact" in ast:
            # Exact match has 50 % penalty if not found
            phrase = ast["exact"].lower().strip()
            return 1.0 if phrase in format_post_for_search(post) else (0 if strict else 0.5)
        if "term" in ast:
            # Compare generic term
            term = ast["term"].lower().strip()
            term_score = 1

            match_user = re.match(r"(?:^|.*\s)user:(\S+).*", term)
            match_source = re.match(r"(?:^|.*\s)source:(\S+).*", term)
            selector_applied = match_source or match_user

            if match_user:
                term_score *= 1 if post.user.lower().startswith(match_user.group(1)) else (0 if strict else 0.3)
            if match_source:
                term_score *= 1 if post.source.lower().startswith(match_source.group(1)) else (0 if strict else 0.3)

            return term_score if selector_applied else None
    elif isinstance(ast, list):
        # Mean of all children
        return mean(filter(lambda x: x is not None, [evaluate_ast(item, post) for item in ast]))

    # Ignore search Tokens such as AND, OR
    return None


def parse_search_terms(ast: Union[list, dict]) -> Iterable[str]:
    if isinstance(ast, dict):
        if "OR" in ast:
            for child in ast["OR"]:
                yield from parse_search_terms(child)
        if "AND" in ast:
            queries = []
            for child in ast["AND"]:
                child_queries = list(parse_search_terms(child))
                queries.append(child_queries)
            queries = filter(lambda x: not not x, queries)
            yield from [' '.join(item) for item in itertools.product(*queries)]
        if "exact" in ast:
            yield ast["exact"]
        if "term" in ast:
            yield ast["term"]
    elif isinstance(ast, list):
        for child in ast:
            yield from parse_search_terms(child)


def format_post_for_search(post: Post) -> str:
    tags = ' '.join([x.name[1:] for x in post.tags])
    return ' '.join([
        post.content_txt,
        tags,
        f"{post.source}:{post.source}",
        f"source:{post.source}",
        f"user:{post.user}",
        post.created_at.isoformat()
    ])


def post_fulltext_score(post_id: int, post_content: str, search_term: str) -> Tuple[int, int]:
    return post_id, fuzzywuzzy.fuzz.token_set_ratio(search_term, post_content)


async def fetch_posts_partial(part: int, parts: int, post_max_id: int) -> List[Post]:
    db = await get_db()
    min_q_id = ceil(post_max_id * (part - 1 ) / parts)
    max_q_id = floor(post_max_id * part / parts)
    posts = await db.post.find_many(where={'is_hidden': False, 'id': {'gte': min_q_id, 'lte': max_q_id}}, include={'tags': True})
    return posts


async def search_posts(fulltext: str, count: int = 40, min_score: int = 15, back_data: Optional[dict] = None) -> List[Tuple[Post, int]]:
    print(f"[*] Search started {fulltext=} {count=} {min_score=}")
    back_data = back_data if back_data is not None else {}
    back_data['time_start'] = time.time()

    strict_search = False

    for command, param in (('strict', None), ('min_score', r'\d+'), ('count', f'\d+')):
        command_re = r"(^.*?)" + f"!{command}" + (f":({param})" if param else "") + r"(.*$)"
        command_search = re.match(command_re, fulltext)
        if not command_search:
            continue
        param_value = command_search.group(2) if param else None
        fulltext = f"{command_search.group(1)} {command_search.group(3 if param else 2)}".strip()
        match command:
            case "strict":
                strict_search = True
            case "min_score":
                min_score = int(param_value)
            case "count":
                count = min(int(param_value), 100)

    fulltext = re.sub(r"\s+", " ", fulltext)
    print(f"[*] Search commands {fulltext=} {strict_search=} {min_score=} {count=}")
    
    if fulltext.startswith('!strict'):
        strict_search = True
        fulltext = fulltext[7:]

    db = await get_db()
    post_max_id = (await db.post.find_first(order={'id': 'desc'})).id
    post_fetch_parts = 32

    all_posts = []
    for posts in await asyncio.gather(*[fetch_posts_partial(x + 1, post_fetch_parts, post_max_id) for x in range(post_fetch_parts)]):
        all_posts.extend(posts)

    back_data['time_goal_db'] = time.time()
    query = parse_query(fulltext)
    post_contents = [(post.id, format_post_for_search(post)) for post in all_posts]
    back_data['time_goal_content'] = time.time()
    matched_ids_score = {}

    for term in parse_search_terms(query):
        if not term.strip():
            continue
        print(f'[*] subsearch {term=}')
        back_data['cnt_search'] = back_data.get('cnt_search', 0) + len(post_contents)
        scorer = partial(post_fulltext_score, search_term=term)
        post_scores = itertools.starmap(scorer, post_contents)

        for post_id, score in post_scores:
            if score < min_score:
                continue
            matched_ids_score[post_id] = max(matched_ids_score.get(post_id, 0), score)
    back_data['time_goal_fulltext'] = time.time()

    matched_posts = [post for post in all_posts if post.id in matched_ids_score]
    back_data['time_goal_matched'] = time.time()

    search_latest = datetime.now(tz=timezone.utc)
    search_earliest = search_latest - timedelta(days=7)

    for post in matched_posts:
        # Penalize posts with small number of tags
        if len(post.tags) < 3:
            matched_ids_score[post.id] *= 0.7
        elif len(post.tags) < 5:
            matched_ids_score[post.id] *= 0.85
        elif len(post.tags) < 1:
            matched_ids_score[post.id] *= 0.55

        # Penalize posts that are outside the search range
        days_outside_search_range = 0
        if post.created_at < search_earliest:
            days_outside_search_range = (search_earliest - post.created_at).days
        elif post.created_at > search_latest:
            days_outside_search_range = (post.created_at - search_latest).days
        if days_outside_search_range > 0:
            matched_ids_score[post.id] *= 0.9
        elif days_outside_search_range > 21:
            matched_ids_score[post.id] *= 0.8
        elif days_outside_search_range > 60:
            matched_ids_score[post.id] *= 0.7
        elif days_outside_search_range > 180:
            matched_ids_score[post.id] *= 0.6

        # Adjust score according to the search query
        post_score_adjustment = evaluate_ast(parse_query(fulltext), post, strict=strict_search)
        matched_ids_score[post.id] *= post_score_adjustment if post_score_adjustment is not None else 1
    back_data['time_goal_eval'] = time.time()

    matched_posts = filter(lambda x: matched_ids_score[x.id] >= min_score, matched_posts)
    matched_posts = sorted(matched_posts, key=lambda x: (matched_ids_score[x.id], x.created_at), reverse=True)[:count]
    result = [(post, round(matched_ids_score[post.id])) for post in matched_posts]
    back_data['time_end'] = time.time()
    back_data['time_total'] = back_data['time_start'] - back_data['time_end']
    
    print(f'[*] Search time DB {int(-1000 * (back_data["time_start"] - back_data["time_goal_db"]))}ms')
    print(f'[*] Search time contents {int(-1000 * (back_data["time_goal_db"] - back_data["time_goal_content"]))}ms')
    print(f'[*] Search time fulltext {int(-1000 * (back_data["time_goal_content"] - back_data["time_goal_fulltext"]))}ms')
    print(f'[*] Search time matched {int(-1000 * (back_data["time_goal_fulltext"] - back_data["time_goal_matched"]))}ms')
    print(f'[*] Search time eval {int(-1000 * (back_data["time_goal_matched"] - back_data["time_goal_eval"]))}ms')
    print(f'[*] Search time end {int(-1000 * (back_data["time_goal_eval"] - back_data["time_end"]))}ms')
    
    return result
