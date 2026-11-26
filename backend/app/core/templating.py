"""Jinja2 rendering with the Django-template features the pages use, plus small response helpers."""
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from math import ceil
from urllib.parse import urlencode

from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import ChainableUndefined, Environment, FileSystemLoader, pass_context
from markupsafe import Markup
from sqlalchemy import func, select

from app.core.config import BASE_DIR
from app.core.security import csrf_token, pop_messages

# ChainableUndefined: a missing attribute renders as nothing, like Django templates (e.g. session.status when session is None)
env = Environment(loader=FileSystemLoader(BASE_DIR / 'templates'), autoescape=True, undefined=ChainableUndefined)

_DATE_CODES = {'M': '%b', 'd': '%d', 'Y': '%Y', 'j': '%-d', 'H': '%H', 'i': '%M'}


def date_filter(value, fmt):
    """Django's |date for the codes the templates use ("M d, Y", "M d")."""
    if not isinstance(value, datetime):
        return ''
    return value.strftime(''.join(_DATE_CODES.get(c, c) for c in fmt))


def floatformat(value, places=0):
    """Django's |floatformat: half-up rounding, '' for missing values."""
    if value is None or value == '':
        return ''
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return ''
    return str(number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


_JS_ESCAPES = {ord(c): f"\\u{ord(c):04X}" for c in '\\\'"<>&=-;`  '}
_JS_ESCAPES.update({z: f"\\u{z:04X}" for z in range(32)})


def escapejs(value):
    """Django's |escapejs: safe inside a quoted JS string in an HTML attribute."""
    return Markup(str(value).translate(_JS_ESCAPES))


@pass_context
def querystring(ctx, **changes):
    """Django's {% querystring %}: the current query with some keys changed; None removes a key."""
    params = [(k, v) for k, v in ctx['request'].query_params.multi_items() if k not in changes]
    params += [(k, v) for k, v in changes.items() if v is not None]
    return '?' + urlencode(params)


env.filters.update(date=date_filter, floatformat=floatformat, escapejs=escapejs)
env.globals.update(static=lambda path: f'/static/{path}', querystring=querystring)


def render(request, template, context=None, status=200):
    token = csrf_token(request)
    ctx = {
        'request': request,
        'user': getattr(request.state, 'user', None),
        'csrf_token': token,
        'csrf_input': Markup(f'<input type="hidden" name="csrfmiddlewaretoken" value="{token}">'),
        'messages': pop_messages(request),
        **(context or {}),
    }
    return HTMLResponse(env.get_template(template).render(ctx), status_code=status)


def redirect(url):
    return RedirectResponse(url, status_code=302)


class Page(list):
    """The slice of Django's Page API the templates use (attributes, since Jinja doesn't call methods)."""

    def __init__(self, items, number, count, num_pages):
        super().__init__(items)
        self.number, self.count, self.num_pages = number, count, num_pages
        self.paginator = self
        self.has_previous = number > 1
        self.has_next = number < num_pages
        self.has_other_pages = num_pages > 1
        self.previous_page_number = number - 1
        self.next_page_number = number + 1


async def paginate(db, stmt, page, per_page):
    """Like Django's Paginator.get_page: a bad page number gives page 1, one past the end gives the last page."""
    count = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    num_pages = max(1, ceil(count / per_page))
    number = min(max(int(page), 1), num_pages) if str(page or '').isdigit() else 1
    items = (await db.scalars(stmt.limit(per_page).offset((number - 1) * per_page))).all()
    return Page(items, number, count, num_pages)


def base_url(request):
    return str(request.base_url).rstrip('/')
