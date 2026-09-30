#!/usr/bin/env python3
"""Exercise actual GTK4 windows against synthetic data, with PNG evidence.

Run under a real Linux desktop or dbus-run-session -- xvfb-run -a. No camera,
recording, model, credentials, autostart file, or real user data is accessed.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.native.testing.fixture_backend import start_fixture
from vantage_linux.client import Client
from vantage_linux.lifecycle import BackendHost
from vantage_linux.application import Application, PAGES, Gtk, GLib
import gi
gi.require_version('Graphene', '1.0')
from gi.repository import Graphene


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fixture = start_fixture()
    temp = tempfile.TemporaryDirectory(prefix='vantage-gtk-smoke-')
    host = BackendHost(Client(f'http://127.0.0.1:{fixture.server_address[1]}'), data_dir=temp.name)
    app = Application(host, [sys.executable, str(Path(__file__).with_name('main.py'))], smoke=True)
    report = {'success': False, 'pages': [], 'checks': [], 'errors': [], 'gtk_version': f'{Gtk.get_major_version()}.{Gtk.get_minor_version()}'}
    def exception_hook(kind, value, tb):
        report['errors'].append(''.join(traceback.format_exception(kind, value, tb)))
        traceback.print_exception(kind, value, tb)
    sys.excepthook = exception_hook
    state = {'index': -1, 'phase': 'boot', 'deadline': time.monotonic() + 80, 'stable': 0, 'action': 0}

    def screenshot(window, name):
        paintable = Gtk.WidgetPaintable.new(window)
        snapshot = Gtk.Snapshot()
        width, height = window.get_width(), window.get_height()
        paintable.snapshot(snapshot, width, height)
        node = snapshot.to_node()
        if node is None:
            raise RuntimeError('Window did not produce a render node')
        rect = Graphene.Rect()
        rect.init(0, 0, width, height)
        texture = window.get_renderer().render_texture(node, rect)
        if not texture.save_to_png(str(args.output_dir / f'{name}.png')):
            raise RuntimeError('Screenshot could not be saved')

    def finish():
        report['success'] = not report['errors'] and len(report['pages']) == len(PAGES)
        (args.output_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if app.window:
            app.window.quit_app()
        else:
            app.quit()
        return GLib.SOURCE_REMOVE

    def tick():
        try:
            window = app.window
            if report['errors']:
                return finish()
            if time.monotonic() > state['deadline']:
                raise RuntimeError(f'Smoke timeout in {state["phase"]}; pending={window.pending if window else None}')
            if not window or not window.connected:
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'boot':
                state['phase'] = 'navigate'
            if state['phase'] == 'navigate':
                state['index'] += 1
                if state['index'] >= len(PAGES):
                    state['phase'] = 'job'
                    window.nav.select_row(window.nav_rows['plan'])
                    return GLib.SOURCE_CONTINUE
                key = PAGES[state['index']][0]
                window.nav.select_row(window.nav_rows[key])
                state['phase'] = 'wait-page'
                state['stable'] = 0
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'wait-page':
                key = PAGES[state['index']][0]
                if window.pending or not window.pages[key].get_first_child():
                    return GLib.SOURCE_CONTINUE
                state['stable'] += 1
                if state['stable'] < 3:
                    return GLib.SOURCE_CONTINUE
                screenshot(window, key)
                report['pages'].append(key)
                state['phase'] = 'navigate'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'job':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                window.create_job()
                state['phase'] = 'wait-job'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'wait-job':
                if not fixture.state['job'] or fixture.state['job']['status'] != 'succeeded' or window.pending:
                    return GLib.SOURCE_CONTINUE
                report['checks'].append('action-plan submit, NDJSON and authoritative saved-result reload')
                window.nav.select_row(window.nav_rows['chat'])
                state['phase'] = 'chat'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'chat':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                window.chat_input.get_buffer().set_text('Synthetic GTK smoke message')
                window.send_chat()
                state['phase'] = 'wait-chat'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'wait-chat':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                if not any(m['content'] == 'Synthetic GTK smoke message' for m in fixture.state['messages']):
                    raise RuntimeError('Native chat send did not reach the fixture')
                window.clear_chat()
                state['phase'] = 'wait-clear'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'wait-clear':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                if len(fixture.state['messages']) != 1:
                    raise RuntimeError('Clear did not restore the authoritative plan context')
                report['checks'].append('chat send, streamed content, context reload and clear')
                window.nav.select_row(window.nav_rows['expenses'])
                state['phase'] = 'recommendations'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'recommendations':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                window.load_recommendations()
                state['phase'] = 'wait-recommendations'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'wait-recommendations':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                if not window.recommendations.get_first_child():
                    raise RuntimeError('Purchase cards were not rendered')
                report['checks'].append('canonical purchase recommendation cards')
                screenshot(window, 'recommendations')
                fixture.state['settings']['settings']['onboarding_completed'] = False
                window.connect_backend()
                state['phase'] = 'onboarding'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'onboarding':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                if window.stack.get_visible_child_name() != 'onboarding':
                    raise RuntimeError('Onboarding was not shown')
                screenshot(window, 'onboarding')
                report['checks'].append('first-run native onboarding and masked credential inputs')
                return finish()
        except Exception as exc:
            report['errors'].append(str(exc))
            traceback.print_exc()
            return finish()
        return GLib.SOURCE_CONTINUE
    GLib.timeout_add(200, tick)
    app.run([sys.argv[0]])
    fixture.shutdown()
    fixture.server_close()
    temp.cleanup()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
