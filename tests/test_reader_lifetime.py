import gc
import json
import sqlite3
from contextlib import closing
import pytest
from codexmeter import compatibility_readers as readers


@pytest.mark.parametrize('reader', ['roots', 'unread'])
@pytest.mark.parametrize('failure', [None, 'schema', 'query', 'invalid', 'account'])
def test_metadata_readers_close_connections(tmp_path, monkeypatch, reader, failure):
    if reader == 'roots' and failure == 'account':
        pytest.skip('Account fencing belongs to unread reader')
    path = tmp_path / ('state_5.sqlite' if reader == 'roots' else 'thread_history_1.sqlite')
    with closing(sqlite3.connect(path)) as db:
        if reader == 'roots':
            db.executescript('CREATE TABLE threads(id TEXT, archived INT, source TEXT); CREATE TABLE thread_spawn_edges(child_thread_id TEXT);')
            db.execute('INSERT INTO threads VALUES (?,0,?)',(None if failure=='invalid' else 't','cli'))
        else:
            db.executescript('CREATE TABLE thread_turns(thread_id TEXT,status TEXT,rollout_ordinal INT);')
            db.execute('INSERT INTO thread_turns VALUES (?,?,1)',('t','weird' if failure=='invalid' else 'completed'))
        db.commit()
    state = tmp_path / '.codex-global-state.json'
    state.write_text(json.dumps({'electron-thread-read-state-v1':{'unreadByIdentity':{'user':{'local:host':['t']}}}}))
    opened=[]
    connect=sqlite3.connect
    class Connection(sqlite3.Connection):
        closed=False
        def execute(self, sql, *args, **kwargs):
            if failure=='query' and sql.startswith('SELECT'):raise sqlite3.OperationalError('probe')
            if failure=='account' and sql.startswith('SELECT'):
                state.write_text('{"electron-thread-read-state-v1":{"unreadByIdentity":{}}}')
            return super().execute(sql,*args,**kwargs)
        def close(self):
            self.closed=True
            return super().close()
    def tracked(*a,**kw):
        conn=connect(*a,**kw,factory=Connection);opened.append(conn);return conn
    monkeypatch.setattr(readers.sqlite3,'connect',tracked)
    if failure=='schema':
        monkeypatch.setattr(readers,'schema',lambda *a:(_ for _ in ()).throw(readers.ContractError(field='inventory')))
    gc.disable()
    try:
        for _ in range(3 if failure is None else 1):
            if failure:
                with pytest.raises((readers.ContractError, sqlite3.Error, LookupError)):
                    readers.read_roots(tmp_path) if reader=='roots' else readers.read_unread_snapshot(tmp_path,{'t'})
            else:
                result=readers.read_roots(tmp_path) if reader=='roots' else readers.read_unread_snapshot(tmp_path,{'t'})[0]
                assert result=={'t'}
            assert opened and all(c.closed for c in opened)
    finally:
        for c in opened:c.close()
        gc.enable()
