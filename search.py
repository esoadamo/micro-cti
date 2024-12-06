import itertools
import re
import time
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import List, Tuple, Union, Iterable, Optional, Dict, Set, TypedDict

import fuzzywuzzy.fuzz
import fuzzywuzzy.process
from lark import Lark, Transformer, v_args, ParseError
from prisma.bases import BasePost
from prisma.models import Post

from db import get_db

SEARCH_GRAMMAR = r"""
?start: expr

?expr: expr term   -> and_expr
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


SEARCH_PARSER = Lark(SEARCH_GRAMMAR, start='start', parser='lalr')
SEARCH_FETCH_STEP = 1000


class PostSearchable(BasePost):
    id: int
    content_search: Optional[str]


class SearchCommands(TypedDict):
    fulltext: str
    strict_search: bool
    fast_search: bool
    min_score: int
    count: int
    search_latest: datetime
    search_earliest: datetime
    search_latest_hard: datetime
    search_earliest_hard: datetime
    final_query: str
    results_max: int


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
        tree = SEARCH_PARSER.parse(query)
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
            return 1.0 if phrase in post.content_search else (0 if strict else 0.5)
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
        return min(filter(lambda x: x is not None, [evaluate_ast(item, post) for item in ast]))

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


async def format_post_for_search(post: Union[PostSearchable, Post], regenerate: bool = False) -> str:
    if not regenerate and post.content_search:
        return post.content_search
    db = await get_db()
    post = await db.post.find_unique(where={'id': post.id}, include={'tags': True})
    tags = ' '.join([x.name[1:] for x in post.tags])
    content_search = ' '.join([
        post.content_txt,
        tags,
        f"{post.source}:{post.source}",
        f"source:{post.source}",
        f"user:{post.user}",
        post.created_at.isoformat()
    ])
    await db.post.update(where={'id': post.id}, data={'content_search': content_search})
    return content_search


def post_fulltext_score(post_id: int, post_content: str, search_term: str) -> Tuple[int, int]:
    return post_id, fuzzywuzzy.fuzz.token_set_ratio(search_term, post_content)


def parse_search_commands(fulltext: str, count: int = 40, min_score: int = 15) -> SearchCommands:
    final_query = fulltext

    strict_search = False
    fast_search = False
    results_max = 100
    search_latest: Optional[datetime] = None
    search_earliest: Optional[datetime] = None

    for command, param in (
            ('strict', None),
            ('fast', None),
            ('min_score', r'\d+'),
            ('count', r'\d+'),
            ('from', r'\d{4}-\d{2}-\d{2}'),
            ('to', r'\d{4}-\d{2}-\d{2}'),
            ('age', r'\d+'),
    ):
        command_re = r"(^.*?)" + f"!{command}" + (f":({param})" if param else "") + r"(.*$)"
        command_search = re.match(command_re, fulltext)
        if not command_search:
            continue
        param_value = command_search.group(2) if param else None
        fulltext = f"{command_search.group(1)} {command_search.group(3 if param else 2)}".strip()
        match command:
            case "strict":
                strict_search = True
            case "fast":
                fast_search = True
            case "min_score":
                min_score = int(param_value)
            case "count":
                count = min(int(param_value), results_max)
            case "from":
                search_earliest = datetime.fromisoformat(param_value)
                search_earliest = search_earliest.replace(tzinfo=timezone.utc)
            case "to":
                search_latest = datetime.fromisoformat(param_value)
                search_latest = search_latest.replace(tzinfo=timezone.utc)
            case "age":
                search_latest = datetime.now(tz=timezone.utc)
                search_earliest = search_latest - timedelta(days=int(param_value))

    if search_latest is None:
        search_latest = datetime.now(tz=timezone.utc)
        final_query = f"!to:{search_latest.strftime('%Y-%m-%d')} {final_query}"
    search_latest.replace(hour=23, minute=59, second=59)
    if search_earliest is None:
        search_earliest = search_latest - timedelta(days=7)
        final_query = f"!from:{search_earliest.strftime('%Y-%m-%d')} {final_query}"
    search_earliest.replace(hour=0, minute=0, second=0)

    search_timespan_hard = (search_latest - search_earliest) * 0.5
    search_latest_hard = search_latest + search_timespan_hard
    search_earliest_hard = search_earliest - search_timespan_hard
    if strict_search:
        search_latest_hard = search_latest
        search_earliest_hard = search_earliest

    assert search_latest is not None
    assert search_earliest is not None
    assert search_latest_hard is not None
    assert search_earliest_hard is not None

    return {
        'fulltext': fulltext,
        'strict_search': strict_search,
        'fast_search': fast_search,
        'min_score': min_score,
        'count': count,
        'search_latest': search_latest,
        'search_earliest': search_earliest,
        'search_latest_hard': search_latest_hard,
        'search_earliest_hard': search_earliest_hard,
        'final_query': final_query,
        'results_max': results_max
    }


async def search_posts(fulltext: str, count: int = 40, min_score: int = 15, back_data: Optional[dict] = None) -> List[Tuple[Post, int]]:
    print(f"[*] Search started {fulltext=} {count=} {min_score=}")
    back_data = back_data if back_data is not None else {}
    back_data['time_start'] = time.time()

    search_commands = parse_search_commands(fulltext, count=count, min_score=min_score)
    fulltext = search_commands['fulltext']
    strict_search = search_commands['strict_search']
    fast_search = search_commands['fast_search']
    min_score = search_commands['min_score']
    count = search_commands['count']
    search_latest = search_commands['search_latest']
    search_earliest = search_commands['search_earliest']
    search_latest_hard = search_commands['search_latest_hard']
    search_earliest_hard = search_commands['search_earliest_hard']
    final_query = search_commands['final_query']
    results_max = search_commands['results_max']

    if fast_search and strict_search:
        raise ParseError("Fast search and strict search cannot be combined")

    fulltext = re.sub(r"\s+", " ", fulltext)
    print(f"[*] Search commands {fulltext=} {strict_search=} {min_score=} {count=}")
    
    if fulltext.startswith('!strict'):
        strict_search = True
        fulltext = fulltext[7:]

    query = parse_query(fulltext)
    search_terms = list(filter(lambda x: x.strip(), parse_search_terms(query)))
    for term in search_terms:
        print(f'[*] subsearch {term=}')

    db = await get_db()
    post_max_id = (await db.post.find_first(order={'id': 'desc'})).id
    matched_ids_score: Dict[int, float] = {}
    while True:
        time_db_start = time.time()

        if fast_search:
            # Fast search is done directly in the database
            if matched_ids_score:
                break  # Fast search runs only once
            posts = []
            for term in search_terms:
                # noinspection SqlNoDataSourceInspection
                posts.extend(await PostSearchable.prisma(client=db).query_raw(
                    f"SELECT id, content_search FROM Post WHERE is_hidden = false AND MATCH(content_search) AGAINST(? IN NATURAL LANGUAGE MODE) LIMIT {results_max * 20}",
                    term
                ))
        else:
            assert search_latest_hard is not None
            assert search_earliest_hard is not None
            posts = await PostSearchable.prisma(client=db).find_many(
                where={
                    'is_hidden': False,
                    'id': {'lte': post_max_id},
                    'OR': [
                        {'created_at': {'gte': search_earliest_hard, 'lte': search_latest_hard}},
                        {'fetched_at': {'gte': search_earliest_hard, 'lte': search_latest_hard}}
                    ]
                },
                take=SEARCH_FETCH_STEP,
                order={'id': 'desc'}
            )
        back_data.setdefault('time_goal_db', 0.0)
        back_data['time_goal_db'] += time.time() - time_db_start

        if not posts:
            break
        post_max_id = posts[-1].id - 1

        time_goal_content_start = time.time()
        post_contents = [(post.id, await format_post_for_search(post)) for post in posts]
        back_data.setdefault('time_goal_content', 0.0)
        back_data['time_goal_content'] += time.time() - time_goal_content_start
        matched_ids_score_curr = {}

        time_goal_fulltext_start = time.time()
        for term in search_terms:
            back_data['cnt_search'] = back_data.get('cnt_search', 0) + len(post_contents)
            scorer = partial(post_fulltext_score, search_term=term)
            post_scores = itertools.starmap(scorer, post_contents)

            for post_id, score in post_scores:
                if score < min_score:
                    continue
                matched_ids_score_curr[post_id] = max(matched_ids_score_curr.get(post_id, 0), score)

        matched_scores_ids: Dict[float, Set[int]] = {}
        for post_id, score in matched_ids_score_curr.items():
            matched_scores_ids.setdefault(score, set()).add(post_id)
        posts_to_add = count * 2
        for score in sorted(matched_scores_ids.keys(), reverse=True):
            for post_id in matched_scores_ids[score]:
                matched_ids_score[post_id] = score
                posts_to_add -= 1
                if posts_to_add <= 0:
                    break
            if posts_to_add <= 0:
                break
        back_data.setdefault('time_goal_fulltext', 0.0)
        back_data['time_goal_fulltext'] += time.time() - time_goal_fulltext_start

    time_goal_matched_start = time.time()
    matched_posts = await db.post.find_many(where={'id': {'in': list(matched_ids_score.keys())}}, include={'tags': True})
    back_data['time_goal_matched'] = time.time() - time_goal_matched_start

    time_goal_eval_start = time.time()

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
    back_data['time_goal_eval'] = time.time() - time_goal_eval_start

    matched_posts = filter(lambda x: matched_ids_score[x.id] >= min_score, matched_posts)
    matched_posts = sorted(matched_posts, key=lambda x: (matched_ids_score[x.id], x.created_at), reverse=True)[:count]
    result = [(post, round(matched_ids_score[post.id])) for post in matched_posts]
    back_data['time_end'] = time.time()
    back_data['time_total'] = back_data['time_start'] - back_data['time_end']
    back_data['query'] = final_query

    print(f'[*] Search time DB {int(1000 * back_data.get("time_goal_db", 0))}ms')
    print(f'[*] Search time contents {int(1000 * back_data.get("time_goal_content", 0))}ms')
    print(f'[*] Search time fulltext {int(1000 * back_data.get("time_goal_fulltext", 0))}ms')
    print(f'[*] Search time matched {int(1000 * back_data.get("time_goal_matched", 0))}ms')
    print(f'[*] Search time eval {int(1000 * back_data.get("time_goal_eval", 0))}ms')
    print(f'[*] Search time total {int(1000 * back_data.get("time_total", 0))}ms')
    print(f'[*] Search results {len(result)}')

    return result
