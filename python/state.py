"""Keep report mappings and uncertain creates in private local files.

These files illustrate recovery for one process. A service should use transactional
storage and coordinate concurrent jobs for the same report.
"""

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

from api import ExampleError, required


class PrivateFiles:
    """Write private state atomically and reserve each create before sending it."""

    def __init__(self):
        self.directory = Path(os.environ.get('MDLOGIC_STATE_DIR', '.local/python'))
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)

    def save(self, name, value, exclusive=False):
        """Replace a complete file, or exclusively create an intent journal.

        A journal must survive an unknown HTTP outcome: its original payload is
        needed to reconcile the write without accidentally creating a duplicate.
        """
        if isinstance(value, bytes):
            raw = value
        else:
            raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
        target = self.directory / name

        if exclusive:
            try:
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'wb') as output:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
            except FileExistsError:
                raise ExampleError(
                    'A create is pending. Reconcile its original target and payload '
                    'before another attempt.'
                ) from None
            return

        with tempfile.NamedTemporaryFile(
            dir=self.directory, prefix='.pending-', delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self):
        """Read the stable project/document mapping; an absent file starts empty."""
        try:
            state = json.loads((self.directory / 'state.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}
        except ValueError:
            raise ExampleError('Local state is invalid. Review it before continuing.') from None
        if not isinstance(state, dict):
            raise ExampleError('Local state is invalid. Review it before continuing.')
        return state

    def refuse_existing(self, name):
        """Require deliberate recovery before creating another private resource."""
        if (self.directory / name).exists():
            raise ExampleError(
                'A saved response exists. Review it before creating another share or destination.'
            )

    def pending(self, number, api, path, body):
        """Reserve a create with its exact origin, target and source payload."""
        operation = {
            'apiOrigin': api.base,
            'method': 'POST',
            'path': path,
            'body': body,
        }
        self.save(f'pending-{number}.json', operation, exclusive=True)

    def done(self, number):
        """Clear a journal only after validating and saving the successful result."""
        (self.directory / f'pending-{number}.json').unlink()


def input_text(fallback):
    """Decode exact UTF-8 source without newline conversion or changing the input."""
    try:
        path = Path(os.environ.get('MDLOGIC_INPUT', fallback))
        return path.read_bytes().decode('utf-8', errors='strict')
    except (OSError, UnicodeError):
        raise ExampleError(
            'Input must be readable UTF-8 text. No mutation was sent; input is unchanged.'
        ) from None


def field(value, key):
    """Read an optional object field without trusting a response's JSON shape."""
    return value.get(key) if isinstance(value, dict) else None


def mapped_path(state, resource):
    """Build an encoded path from stable IDs saved by the earlier scenarios."""
    project_id = quote(required(state.get('projectId'), 'projectId (01)'), safe='')
    path = f'/api/v1/projects/{project_id}'
    if resource == 'document':
        document_id = quote(required(state.get('documentId'), 'documentId (02)'), safe='')
        path += f'/documents/{document_id}'
    return path
