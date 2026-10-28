"""Atomic, local checkpoints for individual successful RAG evaluation calls."""
import hashlib
import json
import os
import uuid
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class Checkpoint:
    def __init__(self, root, signature, resume=False, prepare=None):
        self.signature = signature
        root = Path(root)
        pointer = root / 'current.json'
        runs = (root.parent / 'runs').resolve()
        if resume:
            if not pointer.exists():
                raise ValueError('No resumable evaluation exists. Choose Rerun evaluation first.')
            manifest = json.loads(pointer.read_text())
            if manifest['signature'] != signature:
                raise ValueError('Evaluation configuration has changed (models, data, prompts, or code). Choose Rerun evaluation.')
            self.run_id = manifest['run_id']
            if manifest.get('layout') != 'run-folder':
                raise ValueError('Unsupported checkpoint layout. Restore the experiment before continuing.')
            run = runs / self.run_id
            if run.resolve().parent != runs or run.is_symlink():
                raise ValueError('Invalid evaluation run path.')
            self.directory = run / 'checkpoints'
            if not self.directory.is_dir() or self.directory.is_symlink():
                raise ValueError('Evaluation checkpoints are missing. Restore this experiment before continuing; no model calls were started.')
        else:
            import shutil
            self.run_id = uuid.uuid4().hex
            run = runs / self.run_id
            self.directory = run / 'checkpoints'
            # Prepare the complete experiment before replacing the latest-run pointer.
            # Failure leaves the previous experiment selected and usable.
            run.mkdir(parents=True, exist_ok=False)
            try:
                self.directory.mkdir()
                if prepare is not None:
                    prepare(run, self)
                atomic_json(pointer, {'signature': signature, 'run_id': self.run_id,
                                      'layout': 'run-folder'})
            except BaseException:
                shutil.rmtree(run)
                raise
        self.reused = 0
        self.saved = 0

    def _require_directory(self):
        if not self.directory.is_dir() or self.directory.is_symlink():
            raise OSError('Evaluation checkpoints disappeared. Restore the experiment before continuing.')

    def get(self, key):
        self._require_directory()
        path = self.directory / (digest(key) + '.json')
        if not path.exists():
            return None
        result = json.loads(path.read_text())
        self.reused += 1
        return result

    def put(self, key, value):
        self._require_directory()
        atomic_json(self.directory / (digest(key) + '.json'), value)
        self.saved += 1
