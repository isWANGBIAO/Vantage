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
    report = {'success': False, 'pages': [], 'checks': [], 'errors': [], 'interaction': 'GTK Button clicked signals; async work and authoritative responses verified', 'gtk_version': f'{Gtk.get_major_version()}.{Gtk.get_minor_version()}'}
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

    def click_button(window, captions):
        def walk(widget):
            if isinstance(widget, Gtk.Button) and widget.get_label() in captions:
                widget.emit('clicked')
                return True
            child = widget.get_first_child()
            while child:
                if walk(child):
                    return True
                child = child.get_next_sibling()
            return False
        if not walk(window.stack.get_visible_child()):
            raise RuntimeError(f'Button not found: {captions}')

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
            if window.stack.get_transition_running():
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
                extras = {'plots': [('plots-multiaxis', .5, False), ('plots-radar', 1.0, False)], 'face': [('face-extremes-revealed', 1.0, True)], 'dashboard': [('media-revealed', 1.0, True)], 'settings': [('settings-providers', .4, False), ('settings-voice-image', .8, False)]}.get(key, [])
                state['extras'] = extras
                state['phase'] = 'extra-prepare' if extras else 'navigate'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'extra-prepare':
                name, fraction, reveal = state['extras'][0]
                if reveal:
                    def reveal_images(widget):
                        if isinstance(widget, Gtk.Expander) and any(term in (widget.get_label() or '') for term in ('最近媒体', 'Latest media', '显示照片', 'Reveal photo')):
                            widget.set_expanded(True)
                        child = widget.get_first_child()
                        while child:
                            reveal_images(child)
                            child = child.get_next_sibling()
                    reveal_images(window.stack.get_visible_child())
                state['stable'] = 0
                state['phase'] = 'extra-shot'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'extra-shot':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                name, fraction, reveal = state['extras'][0]
                adjustment = window.stack.get_visible_child().get_vadjustment()
                adjustment.set_value(max(0, adjustment.get_upper() - adjustment.get_page_size()) * fraction)
                state['stable'] += 1
                if state['stable'] < 3:
                    return GLib.SOURCE_CONTINUE
                if reveal:
                    textures = []
                    def collect_textures(widget):
                        if isinstance(widget, Gtk.Picture) and widget.get_paintable() is not None:
                            textures.append(widget.get_paintable())
                        child = widget.get_first_child()
                        while child:
                            collect_textures(child)
                            child = child.get_next_sibling()
                    collect_textures(window.stack.get_visible_child())
                    if not textures or any(texture.get_intrinsic_width() < 32 or texture.get_intrinsic_height() < 32 for texture in textures):
                        raise RuntimeError('Revealed synthetic media did not decode to a real image texture')
                    report['checks'].append(f'{name}: {len(textures)} decoded image textures with nonzero dimensions')
                screenshot(window, name)
                report['checks'].append('scrolled native rendering: ' + name)
                state['extras'].pop(0)
                state['phase'] = 'extra-prepare' if state['extras'] else 'navigate'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'job':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                fixture.state['job_mode'] = 'hold'
                window.generate_button.emit('clicked')
                state['phase'] = 'wait-cancel-job'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'wait-cancel-job':
                if window.pending or not fixture.state['job']:
                    return GLib.SOURCE_CONTINUE
                state['cancelled_id'] = fixture.state['job']['id']
                state['old_plan_id'] = fixture.state['today']['id']
                click_button(window, {'停止任务', 'Cancel job'})
                state['phase'] = 'verify-cancel-job'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'verify-cancel-job':
                if window.pending or fixture.state['job']['status'] != 'cancelled':
                    return GLib.SOURCE_CONTINUE
                if fixture.state['today']['id'] != state['old_plan_id']:
                    raise RuntimeError('Cancelling a job changed the saved plan')
                report['checks'].append('native job Cancel button preserves previous saved plan')
                fixture.state['job_mode'] = 'disconnect'
                window.generate_button.emit('clicked')
                state['phase'] = 'wait-job'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'wait-job':
                if not fixture.state['job'] or fixture.state['job']['status'] != 'succeeded' or window.pending:
                    return GLib.SOURCE_CONTINUE
                report['checks'].append('action-plan submit, intentional stream disconnect/reconnect, NDJSON and authoritative saved-result reload')
                if fixture.state['job']['id'] == state['cancelled_id'] or fixture.state['today']['id'] == state['old_plan_id']:
                    raise RuntimeError('Completed job did not publish a new result identity')
                window.nav.select_row(window.nav_rows['chat'])
                state['phase'] = 'chat'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'chat':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                window.chat_input.get_buffer().set_text('Synthetic GTK smoke message')
                click_button(window, {'发送', 'Send'})
                state['phase'] = 'wait-chat'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'wait-chat':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                if not any(m['content'] == 'Synthetic GTK smoke message' for m in fixture.state['messages']):
                    raise RuntimeError('Native chat send did not reach the fixture')
                click_button(window, {'清空聊天', 'Clear chat'})
                state['phase'] = 'confirm-clear'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'confirm-clear':
                toplevels = Gtk.Window.get_toplevels()
                dialogs = [toplevels.get_item(i) for i in range(toplevels.get_n_items()) if isinstance(toplevels.get_item(i), Gtk.MessageDialog)]
                if not dialogs:
                    return GLib.SOURCE_CONTINUE
                dialogs[0].response(Gtk.ResponseType.CANCEL)
                report['checks'].append('clear conversation native dialog cancelled without mutation')
                click_button(window, {'清空聊天', 'Clear chat'})
                state['phase'] = 'accept-clear'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'accept-clear':
                toplevels = Gtk.Window.get_toplevels()
                dialogs = [toplevels.get_item(i) for i in range(toplevels.get_n_items()) if isinstance(toplevels.get_item(i), Gtk.MessageDialog)]
                if not dialogs:
                    return GLib.SOURCE_CONTINUE
                dialogs[0].response(Gtk.ResponseType.OK)
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
                click_button(window, {'获取采购建议（使用模型）', 'Get recommendations (uses model)'})
                state['phase'] = 'wait-recommendations'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'wait-recommendations':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                if not window.recommendations.get_first_child():
                    raise RuntimeError('Purchase cards were not rendered')
                report['checks'].append('canonical purchase recommendation cards')
                state['stable'] = 0
                state['phase'] = 'recommendation-shot'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'recommendation-shot':
                adjustment = window.stack.get_visible_child().get_vadjustment()
                adjustment.set_value(max(0, adjustment.get_upper() - adjustment.get_page_size()))
                state['stable'] += 1
                if state['stable'] < 3:
                    return GLib.SOURCE_CONTINUE
                screenshot(window, 'recommendations')
                fixture.state['settings']['settings']['onboarding_completed'] = False
                window.connect_backend()
                state['phase'] = 'onboarding'
                state['stable'] = 0
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'onboarding':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                if window.stack.get_visible_child_name() != 'onboarding':
                    raise RuntimeError('Onboarding was not shown')
                state['stable'] += 1
                if state['stable'] < 3:
                    return GLib.SOURCE_CONTINUE
                screenshot(window, 'onboarding')
                report['checks'].append('first-run native onboarding and masked credential inputs')
                click_button(window, {'暂时跳过 AI 配置', 'Skip AI setup for now'})
                state['phase'] = 'wait-onboarding-complete'
                return GLib.SOURCE_CONTINUE
            if state['phase'] == 'wait-onboarding-complete':
                if window.pending:
                    return GLib.SOURCE_CONTINUE
                if not fixture.state['settings']['settings']['onboarding_completed'] or not window.nav.get_sensitive():
                    raise RuntimeError('Onboarding did not complete after the Skip button')
                report['checks'].append('onboarding completion button persists and unlocks navigation')
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
