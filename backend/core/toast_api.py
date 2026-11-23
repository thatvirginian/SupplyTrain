# =============================================================================
# backend/core/toast_api.py
# =============================================================================
# A small client for the Toast API (labor: employees and time entries).
#
# Settings (environment variables, never in code):
#   TOAST_CLIENT_ID       Toast API client identifier
#   TOAST_CLIENT_SECRET   Toast API client secret
#   TOAST_API_HOST        default https://ws-api.toasttab.com
#
# A restaurant is addressed by its Toast restaurant GUID, which is
# locations.store_guid (the locations table comes from the Toast data).
#
#   is_configured()                        -> bool
#   get_employees(restaurant_guid, use_cache=True)
#                                          -> [Employee dict]   (deleted ones included)
#   get_clocked_in(restaurant_guid)        -> {employee guid}   open time entries now
#   display_name(employee)                 -> "Gloria C." (chosen name first)
#
# Nothing from Toast is written to the database here. Answers are kept in this
# process's memory only, briefly: employee lists EMPLOYEE_CACHE_SECONDS,
# clocked-in lists CLOCK_CACHE_SECONDS.
#
# Raises ToastError when Toast cannot be reached or refuses. Callers decide what
# to do then (the sign-in box simply shows everyone).
# The bearer token is cached in this process until shortly before it expires.
# =============================================================================

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TIMEOUT_SECONDS     = 10
CLOCK_CACHE_SECONDS    = 60
EMPLOYEE_CACHE_SECONDS = 300

_lock        = threading.Lock()
_token       = {'value': None, 'expires': 0.0}
_clock_cache = {}            # restaurant guid -> (fetched_at, set of employee guids)
_emp_cache   = {}            # restaurant guid -> (fetched_at, [employees])


class ToastError(Exception):
    pass


def _host():
    return (os.environ.get('TOAST_API_HOST') or 'https://ws-api.toasttab.com').rstrip('/')


def is_configured():
    return bool(os.environ.get('TOAST_CLIENT_ID') and os.environ.get('TOAST_CLIENT_SECRET'))


def _request(method, path, *, body=None, headers=None, params=None):
    url = _host() + path
    if params:
        url += '?' + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Accept', 'application/json')
    if data is not None:
        req.add_header('Content-Type', 'application/json')
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode()[:300]
        except Exception:
            pass
        raise ToastError(f'Toast answered {e.code} for {path}: {detail}') from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ToastError(f'Could not reach Toast: {e}') from None
    try:
        return json.loads(raw or b'null')
    except ValueError:
        raise ToastError(f'Toast sent something that is not JSON for {path}') from None


def _bearer():
    if not is_configured():
        raise ToastError('The Toast API is not set up (TOAST_CLIENT_ID / TOAST_CLIENT_SECRET)')
    with _lock:
        if _token['value'] and time.time() < _token['expires']:
            return _token['value']
        res = _request('POST', '/authentication/v1/authentication/login', body={
            'clientId':       os.environ['TOAST_CLIENT_ID'],
            'clientSecret':   os.environ['TOAST_CLIENT_SECRET'],
            'userAccessType': 'TOAST_MACHINE_CLIENT',
        })
        tok = (res or {}).get('token') or {}
        if not tok.get('accessToken'):
            raise ToastError('Toast login did not return a token')
        _token['value']   = tok['accessToken']
        _token['expires'] = time.time() + max(60, int(tok.get('expiresIn') or 3600) - 300)
        return _token['value']


def _get(path, restaurant_guid, params=None):
    return _request('GET', path, params=params, headers={
        'Authorization':                f'Bearer {_bearer()}',
        'Toast-Restaurant-External-ID': str(restaurant_guid),
    })


def display_name(e):
    first = (e.get('chosenName') or e.get('firstName') or '').strip()
    last = (e.get('lastName') or '').strip()
    return (f'{first} {last[0]}.' if last else first) or 'Unknown'


def get_employees(restaurant_guid, use_cache=True):
    """Every employee of one restaurant (deleted ones carry deleted = true)."""
    now = time.time()
    hit = _emp_cache.get(str(restaurant_guid))
    if use_cache and hit and now - hit[0] < EMPLOYEE_CACHE_SECONDS:
        return list(hit[1])
    out, page_token = [], None
    for _ in range(50):                               # safety stop
        params = {'pageToken': page_token} if page_token else None
        res = _get('/labor/v1/employees', restaurant_guid, params)
        if isinstance(res, list):                     # the documented shape: a plain list
            out.extend(res)
            break
        out.extend((res or {}).get('employees') or [])
        page_token = (res or {}).get('pageToken') or (res or {}).get('nextPageToken')
        if not page_token:
            break
    _emp_cache[str(restaurant_guid)] = (now, out)
    return list(out)


def get_clocked_in(restaurant_guid, use_cache=True):
    """GUIDs of the employees with an open time entry (clocked in, not out) right now."""
    now = time.time()
    if use_cache:
        hit = _clock_cache.get(str(restaurant_guid))
        if hit and now - hit[0] < CLOCK_CACHE_SECONDS:
            return set(hit[1])
    end   = datetime.now(timezone.utc) + timedelta(minutes=5)
    start = end - timedelta(hours=36)                 # long shifts and overnight work
    fmt = lambda d: d.strftime('%Y-%m-%dT%H:%M:%S.000+0000')
    res = _get('/labor/v1/timeEntries', restaurant_guid, {'startDate': fmt(start), 'endDate': fmt(end)})
    guids = set()
    for te in res or []:
        if te.get('deleted') or te.get('outDate') or not te.get('inDate'):
            continue
        ref = te.get('employeeReference') or {}
        if ref.get('guid'):
            guids.add(ref['guid'])
    _clock_cache[str(restaurant_guid)] = (now, guids)
    return set(guids)
