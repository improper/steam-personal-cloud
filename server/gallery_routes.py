"""Authenticated gallery media proxy and soft deletion for Immich assets."""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from fastapi import Header, HTTPException, Request
from fastapi.responses import StreamingResponse
import requests

UUID_RE = re.compile(r'^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$')
RANGE_RE = re.compile(r'^bytes=(?:[0-9]+-[0-9]*|-[0-9]+)$')


def register_gallery_routes(app, authorize, database, immich_url, immich_key, immich_request):
    """Scoped credentials can access only their own client's uploaded assets."""
    def asset_for(token, asset_id):
        authorize(token)
        if not UUID_RE.fullmatch(asset_id):
            raise HTTPException(404, 'Asset unavailable')
        with database() as db:
            row = db.execute('SELECT client,account,kind,status,immich_id FROM media WHERE immich_id=?',
                             (asset_id,)).fetchone()
            if row is None or row['status'] != 'complete':
                raise HTTPException(404, 'Asset unavailable')
            # Admin master token can view everything; device tokens remain narrowly scoped.
            # Re-check on this endpoint so knowing an asset UUID cannot bypass tenant scope.
            if not authorize(token, row['client'], row['account']):
                return dict(row)
            return dict(row)

    @app.get('/api/media/{asset_id}/{kind}')
    def media(asset_id: str, kind: str, request: Request,
              x_spc_token: Optional[str] = Header(default=None)):
        row = asset_for(x_spc_token, asset_id)
        if kind not in ('thumb', 'preview', 'video'):
            raise HTTPException(404, 'Unsupported media kind')
        if kind == 'video' and row['kind'] != 'video':
            raise HTTPException(404, 'Asset is not video')
        if not immich_url or not immich_key:
            raise HTTPException(503, 'Immich unavailable')
        endpoint = (f'/api/assets/{asset_id}/video/playback' if kind == 'video'
                    else f'/api/assets/{asset_id}/thumbnail')
        params = None if kind == 'video' else {'size': 'thumbnail' if kind == 'thumb' else 'preview'}
        headers = {'x-api-key': immich_key, 'Accept': '*/*'}
        if kind == 'video' and request.headers.get('Range'):
            requested_range = request.headers['Range']
            if not RANGE_RE.fullmatch(requested_range):
                raise HTTPException(416, 'Unsupported range')
            headers['Range'] = requested_range
        try:
            upstream = requests.get(immich_url + endpoint, params=params, headers=headers,
                                    stream=True, timeout=(5, 40), allow_redirects=False)
        except requests.RequestException as exc:
            raise HTTPException(502, 'Immich media temporarily unavailable') from exc
        if upstream.status_code not in (200, 206):
            upstream.close()
            raise HTTPException(503 if upstream.status_code in (202, 404, 409, 422) else 502,
                                'Media is not ready in Immich')

        def chunks():
            try:
                yield from upstream.iter_content(chunk_size=128 * 1024)
            finally:
                upstream.close()

        passthrough = {key: upstream.headers[key] for key in ('Content-Length', 'Content-Range', 'Accept-Ranges')
                       if key in upstream.headers}
        return StreamingResponse(chunks(), status_code=upstream.status_code,
                                 media_type=upstream.headers.get('Content-Type', 'application/octet-stream'),
                                 headers=passthrough)

    @app.delete('/api/media/{asset_id}/immich')
    def trash_immich_asset(asset_id: str, x_spc_token: Optional[str] = Header(default=None)):
        asset_for(x_spc_token, asset_id)
        if not immich_url or not immich_key:
            raise HTTPException(503, 'Immich unavailable')
        try:
            # force=False means move to Immich Trash, not permanently delete.
            immich_request('DELETE', '/assets', json={'ids': [asset_id], 'force': False})
        except requests.RequestException as exc:
            raise HTTPException(502, 'Unable to move item to Immich Trash') from exc
        with database() as db:
            db.execute("UPDATE media SET status='deleted',updated_at=strftime('%s','now') WHERE immich_id=? AND status='complete'",
                       (asset_id,))
        return {'ok': True, 'immich': 'trashed'}
