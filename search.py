import itertools
import re
import time
from datetime import datetime, timedelta, timezone
from functools import reduce
from statistics import mean
from typing import List, Tuple, Union, Iterable, Optional

import fuzzywuzzy
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


def evaluate_ast(ast: Union[list, dict], post: Post, strict: bool = False) -> float:
    if isinstance(ast, dict):
        if "OR" in ast:
            # OR score is counted as sum of the children
            return sum(evaluate_ast(child, post) for child in ast["OR"])
        if "AND" in ast:
            # AND score is counted as product of the children
            return reduce(lambda a, b: a * b, [evaluate_ast(child, post) for child in ast["AND"]])
        if "exact" in ast:
            # Exact match has 50 % penalty if not found
            phrase = ast["exact"]
            return 1.0 if phrase.lower() in format_post_for_search(post) else (0 if strict else 0.5)
        if "term" in ast:
            # Compare generic term
            term = ast["term"]

            match_user = re.match(r"(?:^|.*\s)user:(\S+).*", term)
            match_source = re.match(r"(?:^|.*\s)source:(\S+).*", term)

            if match_user:
                return 1 if post.user.lower().startswith(match_user.group(1).lower()) else (0 if strict else 0.3)
            if match_source:
                return 1 if post.source.lower().startswith(match_source.group(1).lower()) else (0 if strict else 0.3)

            return 1
    elif isinstance(ast, list):
        # Mean of all children
        return mean(evaluate_ast(item, post) for item in ast)
    return 1


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


async def search_posts(fulltext: str, back_data: Optional[dict] = None) -> List[Tuple[Post, int]]:
    back_data = back_data if back_data is not None else {}
    back_data['time_start'] = time.time()

    strict_search = False
    if fulltext.startswith('!strict'):
        strict_search = True
        fulltext = fulltext[7:]

    db = await get_db()
    all_posts = await db.post.find_many(where={'is_hidden': False}, include={'tags': True})
    query = parse_query(fulltext)
    post_contents = [(post.id, format_post_for_search(post)) for post in all_posts]
    matched_ids_score = {}

    for term in parse_search_terms(query):
        if not term.strip():
            continue
        back_data['cnt_search'] = back_data.get('cnt_search', 0) + len(post_contents)
        # noinspection PyUnresolvedReferences
        matched = fuzzywuzzy.process.extract(term, post_contents, limit=40, scorer=fuzzywuzzy.fuzz.token_set_ratio)
        for (post_id, post_content), score in matched:
            matched_ids_score[post_id] = max(matched_ids_score.get(post_id, 0), score)
    matched_posts = [post for post in all_posts if post.id in matched_ids_score]

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
        matched_ids_score[post.id] *= evaluate_ast(parse_query(fulltext), post, strict=strict_search)

    matched_posts = filter(lambda x: matched_ids_score[x.id] > 1, matched_posts)
    matched_posts = sorted(matched_posts, key=lambda x: (matched_ids_score[x.id], x.created_at), reverse=True)
    result = [(post, round(matched_ids_score[post.id])) for post in matched_posts]
    back_data['time_end'] = time.time()
    back_data['time_total'] = back_data['time_start'] - back_data['time_end']
    return result
