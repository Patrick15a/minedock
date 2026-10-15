from __future__ import annotations

import collections
import os
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import psutil

from . import core, modscan


class Manager:
    def __init__(self):
        self.lock = threading.RLock()
        self.processes = {}
        self.logs = collections.defaultdict(lambda: collections.deque(maxlen=1200))
        self.sequence = collections.defaultdict(int)
        self.jobs = {}
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='install')
        self.closing = False

    def log(self, sid, text):
        with self.lock:
            for line in str(text).splitlines():
                self.sequence[sid] += 1
                self.logs[sid].append({'id': self.sequence[sid], 'text': line[:6000]})

    def running(self, sid):
        proc = self.processes.get(sid)
        return proc is not None and proc.poll() is None

    def idle(self, sid):
        if self.running(sid) or self.jobs.get(sid, {}).get('state') == 'running':
            raise ValueError('Server zuerst stoppen bzw. laufenden Vorgang abwarten.')

    def submit(self, sid, label, fn):
        with self.lock:
            if self.closing:
                raise ValueError('Panel wird beendet.')
            self.idle(sid)
            self.jobs[sid] = {'state': 'running', 'label': label, 'error': None}
            self.log(sid, f'[MineDock] {label}')
            def run():
                try:
                    fn()
                    with self.lock:
                        self.jobs[sid] = {'state': 'done', 'label': label, 'error': None}
                    self.log(sid, '[MineDock] Vorgang abgeschlossen.')
                except Exception as exc:
                    message = str(exc).replace(core.CF_KEY, '***') if core.CF_KEY else str(exc)
                    with self.lock:
                        self.jobs[sid] = {'state': 'error', 'label': label, 'error': message[:1500]}
                    self.log(sid, f'[MineDock] Fehler: {message}')
            self.pool.submit(run)

    def snapshot(self, config):
        sid = config['id']
        with self.lock:
            active = self.running(sid)
            job = self.jobs.get(sid)
            memory = 0
            if active:
                try:
                    memory = round(psutil.Process(self.processes[sid].pid).memory_info().rss / 1048576)
                except psutil.Error:
                    pass
            public = {k: v for k, v in config.items() if k not in ('mod_scan', 'mod_sources', 'mod_overrides', 'mod_server_reference', 'mod_manifest_key')}
            return {**public, 'state': 'busy' if job and job['state'] == 'running' else 'running' if active else 'stopped',
                    'memory_used_mb': memory, 'job': job}

    def start(self, sid):
        with self.lock:
            self.idle(sid)
            cfg = core.get(sid)
            if cfg.get('archived'):
                raise ValueError('Archivierter Server.')
            if not cfg.get('installed') or cfg.get('missing'):
                raise ValueError('Installation abschließen und fehlende Dateien hochladen.')
            if not cfg.get('eula'):
                raise ValueError('Minecraft-EULA muss vor dem Start bestätigt werden.')
            if os.name != 'posix':
                raise ValueError('Minecraft-Prozesse werden ausschließlich auf Linux gestartet.')
            used = sum(core.get(i)['memory_mb'] + 768 for i in self.processes if self.running(i))
            if used + cfg['memory_mb'] + 768 > core.BUDGET_MB:
                raise ValueError('Das gemeinsame RAM-Budget reicht nicht aus (inklusive 768 MB Reserve je Server).')
            if psutil.virtual_memory().available < (cfg['memory_mb'] + 768) * 1048576:
                raise ValueError('Auf dem Host ist aktuell nicht genügend freier RAM verfügbar.')
            directory = core.folder(sid)
            (directory / 'eula.txt').write_text('eula=true\n', encoding='utf8')
            args = cfg.get('launch', [])
            if not args:
                raise ValueError('Keine startfähige Serverinstallation vorhanden.')
            java = core.JAVA.get(cfg['java'])
            if not java or not os.path.isfile(java):
                raise ValueError('Die ausgewählte Java-Version ist auf dem Host nicht konfiguriert.')
            modscan.run(sid, self)
            cmd = [java, '-Xms512M', f"-Xmx{cfg['memory_mb']}M", *args, 'nogui']
            proc = subprocess.Popen(cmd, cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding='utf8', errors='replace',
                                    bufsize=1, start_new_session=True, env=core.child_env())
            self.processes[sid] = proc
            self.log(sid, '[MineDock] Java-Prozess gestartet. Den Minecraft-Startstatus zeigt die Konsole.')
            def collect():
                for line in proc.stdout:
                    self.log(sid, line.rstrip())
                code = proc.wait()
                self.log(sid, f'[MineDock] Prozess beendet (Exit-Code {code}).')
                proc.stdout.close()
                proc.stdin.close()
            threading.Thread(target=collect, daemon=True).start()

    def command(self, sid, value):
        with self.lock:
            if not self.running(sid):
                raise ValueError('Server läuft nicht.')
            if not value or len(value) > 1000 or any(ord(c) < 32 for c in value):
                raise ValueError('Ungültiger Konsolenbefehl.')
            try:
                self.processes[sid].stdin.write(value + '\n')
                self.processes[sid].stdin.flush()
            except (OSError, ValueError):
                raise ValueError('Serverkonsole ist nicht mehr verfügbar.')
            self.log(sid, '> ' + value)

    def stop(self, sid):
        with self.lock:
            proc = self.processes.get(sid)
            if not proc or proc.poll() is not None:
                return
            self.command(sid, 'stop')
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.log(sid, '[MineDock] Keine Antwort auf stop; Prozess wird beendet.')
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)

    def shutdown(self):
        self.closing = True
        self.pool.shutdown(wait=True, cancel_futures=True)
        for sid in list(self.processes):
            self.stop(sid)


manager = Manager()
