"""Interactive DSC evaluation in NOMAD's Jupyter (NORTH): pick windows with the mouse.

In a notebook opened with "OPEN IN JUPYTER" on the project page:

    %matplotlib widget
    from nomad_dsc_trios.north import DSCEvaluator
    DSCEvaluator()

* Folder: every folder of your projects with DSC entries (projects are mounted under ~/uploads).
* Curve: one DSC run of the folder; the plot shows cooling (top) and heating (bottom) of the selected
  cycle with the tangent construction, computed with the same code as NOMAD.
* Drag across a peak (mouse, from baseline point to baseline point) to set its window: the mode
  switches to semi-automatic, the other ramp keeps the automatic windows. A new window replaces the
  window it overlaps, otherwise it is added (several peaks). "Start from automatic" copies the
  windows found automatically, "Clear" removes the windows of a ramp.
* "Save to NOMAD" writes mode, cycle and windows into the entry (<run>.archive.json) and lets NOMAD
  process it; reload the entry page to see the result there.
* "Results of this folder" shows the values stored in NOMAD for all DSC entries of the folder and
  saves them as 0000_dsc_results.csv into the folder.

Needs ipympl in the Jupyter image (matplotlib widget backend).
"""

import glob
import gzip
import io
import json
import os

import numpy as np

from nomad_dsc_trios import evaluation_nomad as EV

DSC_DEF = 'nomad_dsc_trios.schema_packages.dsc.DSC_SMA'
UPLOADS = os.path.expanduser('~/uploads')
CSV_NAME = '0000_dsc_results.csv'


# ------------------------------------------------------------------ NOMAD API
# NORTH passes NOMAD_CLIENT_URL / NOMAD_CLIENT_ACCESS_TOKEN only in its classic mode; otherwise the
# API is looked for at these addresses and the user logs in once per session in the GUI.
API_CANDIDATES = ('http://nomad.fzu.cz/api', 'http://nomad.fzu.cz/nomad-oasis/api')
_session = {'api': None, 'token': None}


try:  # share login and project names with the general Jupyter helpers, if installed
    from nomad_dept18_jupyter import nomad as _NJ
except ImportError:
    _NJ = None


def find_api():
    """Base URL '<...>/api/v1' of a NOMAD API that answers, or None."""
    if _session['api']:
        return _session['api']
    if _NJ is not None:
        try:
            _session['api'] = _NJ.api()
            return _session['api']
        except Exception:  # noqa: S110 (fall back to the own search)
            pass
    import requests  # noqa: PLC0415

    env = os.environ.get('NOMAD_CLIENT_URL')
    for base in ([env] if env else []) + [os.environ.get('DSC_NOMAD_API', '')] + list(API_CANDIDATES):
        if not base:
            continue
        url = base.rstrip('/') + ('' if base.rstrip('/').endswith('/v1') else '/v1')
        try:
            r = requests.get(f'{url}/info', timeout=5)
            if r.ok and 'version' in r.json():
                _session['api'] = url
                return url
        except Exception:  # noqa: S112 (try the next address)
            continue
    return None


def token():
    shared = _NJ.token() if _NJ is not None else None
    return _session['token'] or shared or os.environ.get('NOMAD_CLIENT_ACCESS_TOKEN')


def login(user, password):
    import requests  # noqa: PLC0415

    api = find_api()
    if api is None:
        raise RuntimeError('NOMAD API not reachable from Jupyter')
    r = requests.post(f'{api}/auth/token', timeout=30,
                      data={'grant_type': 'password', 'username': user, 'password': password})
    r.raise_for_status()
    _session['token'] = r.json()['access_token']
    if _NJ is not None:
        _NJ._session.update(api=api, token=_session['token'])
    return api


def _posix(path):
    """Relative path with '/' (NOMAD paths; on Windows os.path gives backslashes)."""
    return path.replace(os.sep, '/')


def in_north():
    """True in NOMAD's own Jupyter (NORTH), False on a PC with a downloaded copy of a project."""
    return bool(os.environ.get('JUPYTERHUB_USER'))


def folder_label(folder):
    """'Project name/sub/folder' for a mounted folder (project names remembered by the helpers)."""
    rel = _posix(os.path.relpath(folder, UPLOADS))
    pid, _, rest = rel.partition('/')
    names = {}
    if _NJ is not None:
        try:
            names = _NJ._load_names()
        except Exception:  # noqa: S110
            pass
    name = names.get(pid[-22:], pid)
    return f'{name}/{rest}' if rest else name


# ------------------------------------------------------------------ files
def upload_root(path):
    """Mounted project folder (~/uploads/<name>-<upload id>) that contains `path`."""
    path = os.path.abspath(path)
    while True:
        parent = os.path.dirname(path)
        if os.path.basename(parent) == 'uploads' or parent == path:
            return path
        path = parent


def upload_id(root):
    return os.path.basename(root)[-22:]  # mounted as <slugified name>-<22 character upload id>


def is_dsc_entry(path):
    try:
        with open(path) as f:
            return str(json.load(f).get('data', {}).get('m_def', '')) == DSC_DEF
    except (OSError, ValueError):
        return False


def dsc_entries(folder):
    return sorted(p for p in glob.glob(os.path.join(folder, '*.archive.json')) if is_dsc_entry(p))


def dsc_folders(base=UPLOADS):
    folders = []
    for dirpath, _, files in os.walk(base):
        if any(f.endswith('.archive.json') for f in files) and dsc_entries(dirpath):
            folders.append(dirpath)
    return sorted(folders)


class Run:
    """One DSC entry (<run>.archive.json) and its TRIOS export."""

    def __init__(self, path):
        self.path = path
        self.root = upload_root(path)
        with open(path) as f:
            self.doc = json.load(f)
        self.data = self.doc.get('data', {})
        self._segments = self._exo_up = None

    @property
    def name(self):
        return os.path.basename(self.path)[:-len('.archive.json')]

    @property
    def rel(self):
        return _posix(os.path.relpath(self.path, self.root))

    def load(self):
        if self._segments is None:
            from nomad_dsc_trios.trios import read_trios_csv, read_trios_json  # noqa: PLC0415

            f = os.path.join(self.root, self.data['data_file'])
            low = f.lower()
            if low.endswith('.gz'):
                with gzip.open(f) as g:
                    d = read_trios_json(json.load(io.TextIOWrapper(g, encoding='utf-8-sig')), f)[0]
            elif low.endswith('.json'):
                with open(f, encoding='utf-8-sig') as g:
                    d = read_trios_json(json.load(g), f)[0]
            else:
                with open(f, encoding='utf-8-sig') as g:
                    d = read_trios_csv(g.read().splitlines(), f)[0]
            self._segments = d['measurement']['segments']
            self._exo_up = EV.exo_up_of(d.get('instrument_settings') or {})
        return self._segments, self._exo_up

    def settings(self):
        return EV.find_settings_in(self.root, os.path.dirname(self.rel))

    def evaluation_dict(self):
        return dict(self.data.get('evaluation') or {})

    def save_evaluation(self, ev):
        """Write the evaluation section into the entry: via the NOMAD API (processed at once) or
        into the mounted file (processed on the next reprocessing). Returns a message."""
        self.data['evaluation'] = {**(self.data.get('evaluation') or {}), **ev}
        self.doc['data'] = self.data
        text = json.dumps(self.doc, indent=2)
        tok = token()
        api = find_api() if tok else None
        if api and tok:
            try:
                import requests  # noqa: PLC0415

                folder = _posix(os.path.dirname(self.rel))
                r = requests.put(f'{api}/uploads/{upload_id(self.root)}/raw/{folder}',
                                 params={'file_name': os.path.basename(self.path), 'wait_for_processing': True},
                                 data=text.encode(), headers={'Authorization': f'Bearer {tok}'}, timeout=300)
                r.raise_for_status()
                return 'saved and processed by NOMAD'
            except Exception as e:  # fall back to the mounted file
                err = f' (API: {e})'
        else:
            err = ''
        with open(self.path, 'w') as f:
            f.write(text)
        if not in_north():  # a copy on a PC: the file is not the one in NOMAD
            return (f'NOT saved in NOMAD{err}: only the copy on this PC was changed. '
                    'Log in above (NOMAD user name and password) and save again.')
        hint = '' if tok else ' (log in above to let NOMAD process it at once)'
        return f'saved to the file{err}; click ⟳ on the project page to process it{hint}'


# ------------------------------------------------------------------ GUI
class DSCEvaluator:
    def __init__(self, folder=None):
        import ipywidgets as W  # noqa: PLC0415
        import matplotlib.pyplot as plt  # noqa: PLC0415
        from matplotlib.widgets import SpanSelector  # noqa: PLC0415

        self.W = W
        folders = dsc_folders()
        if folder:
            folder = os.path.abspath(os.path.expanduser(folder))
            folders = sorted(set(folders) | {folder})
        self.w_folder = W.Dropdown(options=[(folder_label(f), f) for f in folders],
                                   value=folder or (folders[0] if folders else None),
                                   description='Folder', layout=W.Layout(width='70%'))
        self.w_run = W.Dropdown(description='Curve', layout=W.Layout(width='45%'))
        self.w_prev, self.w_next = W.Button(description='◀', layout=W.Layout(width='40px')), \
            W.Button(description='▶', layout=W.Layout(width='40px'))
        self.w_mode = W.ToggleButtons(options=['automatic', 'semi-automatic'], description='Mode')
        self.w_cycle = W.BoundedIntText(value=1, min=1, max=99, description='Cycle', layout=W.Layout(width='150px'))
        self.w_auto = W.Button(description='Start from automatic', tooltip='copy the windows found automatically')
        self.w_clear_c = W.Button(description='Clear cooling windows')
        self.w_clear_h = W.Button(description='Clear heating windows')
        self.w_save = W.Button(description='Save to NOMAD', button_style='primary', icon='save')
        self.w_table = W.Button(description='Results of this folder', icon='table')
        self.w_user = W.Text(description='NOMAD user', layout=W.Layout(width='260px'))
        self.w_pw = W.Password(description='Password', layout=W.Layout(width='260px'))
        self.w_login = W.Button(description='Log in', icon='sign-in')
        self.w_login_msg = W.HTML('<i>Log in once per session so that "Save to NOMAD" processes the curve at '
                                  'once and "Results of this folder" works.</i>')
        self.login_box = W.HBox([self.w_user, self.w_pw, self.w_login, self.w_login_msg])
        self.login_box.layout.display = 'none' if token() else None
        self.w_login.on_click(lambda _: self._login())
        self.w_info = W.HTML()
        self.w_results = W.HTML()
        self.w_msg = W.HTML()
        self.out_table = W.Output()

        plt.ioff()
        self.fig, (self.ax_c, self.ax_h) = plt.subplots(2, 1, figsize=(9, 7))
        plt.ion()
        self.fig.canvas.header_visible = False
        self.spans = [SpanSelector(ax, (lambda a, b, r=r: self._on_span(r, a, b)), 'horizontal', useblit=True,
                                   props={'alpha': 0.2, 'facecolor': '#ff7f0e'}, minspan=1.0)
                      for ax, r in ((self.ax_c, 'cooling'), (self.ax_h, 'heating'))]

        self.windows = {'cooling': [], 'heating': []}
        self.runs, self.run = [], None
        self.w_folder.observe(lambda _: self._load_folder(), 'value')
        self.w_run.observe(lambda _: self._load_run(), 'value')
        self.w_prev.on_click(lambda _: self._step(-1))
        self.w_next.on_click(lambda _: self._step(1))
        self.w_mode.observe(lambda _: self._update(), 'value')
        self.w_cycle.observe(lambda _: self._update(), 'value')
        self.w_auto.on_click(lambda _: self._from_auto())
        self.w_clear_c.on_click(lambda _: self._clear('cooling'))
        self.w_clear_h.on_click(lambda _: self._clear('heating'))
        self.w_save.on_click(lambda _: self._save())
        self.w_table.on_click(lambda _: self._folder_table())

        self.box = W.VBox([
            self.login_box,
            W.HBox([self.w_folder]),
            W.HBox([self.w_run, self.w_prev, self.w_next, self.w_info]),
            W.HBox([self.w_mode, self.w_cycle]),
            W.HBox([self.w_auto, self.w_clear_c, self.w_clear_h]),
            W.HTML('<i>Drag across a peak in a plot to add a window for that ramp.</i>'),
            self.fig.canvas,
            self.w_results,
            W.HBox([self.w_save, self.w_table]),
            self.w_msg,
            self.out_table,
        ])
        if self.w_folder.value:
            self._load_folder()
        else:
            self.w_msg.value = f'No DSC entries found under {UPLOADS}. Open Jupyter from the project page.'

    def _ipython_display_(self):
        from IPython.display import display  # noqa: PLC0415

        display(self.box)

    def _login(self):
        try:
            api = login(self.w_user.value.strip(), self.w_pw.value)
        except Exception as e:
            self.w_login_msg.value = f'<span style="color:#b00">login failed: {e}</span>'
            return
        self.w_pw.value = ''
        self.login_box.layout.display = 'none'
        self.w_msg.value = f'logged in to {api}'
        if _NJ is not None:  # project names instead of ids in the folder list
            try:
                _NJ._project_records(refresh=True)
                value = self.w_folder.value
                self.w_folder.unobserve_all('value')
                self.w_folder.options = [(folder_label(f), f) for _, f in self.w_folder.options]
                self.w_folder.value = value
                self.w_folder.observe(lambda _: self._load_folder(), 'value')
            except Exception:  # noqa: S110
                pass

    # ---------------------------------------------------------------- state
    def _load_folder(self):
        self.runs = [Run(p) for p in dsc_entries(self.w_folder.value)]
        self.w_run.options = [(r.name, i) for i, r in enumerate(self.runs)]
        self.w_run.value = 0 if self.runs else None
        self._load_run()

    def _step(self, d):
        if self.runs:
            self.w_run.value = (self.w_run.value + d) % len(self.runs)

    def _load_run(self):
        if self.w_run.value is None:
            return
        self.run = self.runs[self.w_run.value]
        ev = self.run.evaluation_dict()
        settings, spath = self.run.settings()
        mode = ev.get('mode') or settings.get('mode') or EV.DEFAULT_MODE
        self.windows = {'cooling': [], 'heating': []}
        for w in ev.get('windows') or []:
            if w.get('ramp') in self.windows and w.get('T1') is not None and w.get('T2') is not None:
                self.windows[w['ramp']].append((w['T1'], w['T2']))
        self.w_info.value = (f'&nbsp; stored mode: <b>{mode}</b>; folder settings: '
                             f"{spath or 'none'}")
        self._silent(self.w_cycle, int(ev.get('cycle') or settings.get('cycle') or EV.DEFAULT_CYCLE))
        self._silent(self.w_mode, 'semi-automatic' if mode == 'semi-automatic' and any(self.windows.values())
                     else 'automatic')
        self.w_msg.value = ''
        self._update()

    def _silent(self, widget, value):
        widget.unobserve_all('value')
        widget.value = value
        widget.observe(lambda _: self._update(), 'value')

    def _ev(self, mode):
        return {**self.run.evaluation_dict(), 'mode': mode, 'cycle': self.w_cycle.value,
                'windows': [{'ramp': r, 'T1': a, 'T2': b} for r, ws in self.windows.items() for a, b in ws]}

    def _evaluate(self, mode):
        segments, exo_up = self.run.load()
        settings, _ = self.run.settings()
        return EV.evaluate(segments, exo_up, self._ev(mode), settings, mode=mode), exo_up

    # ---------------------------------------------------------------- actions
    def _on_span(self, ramp, a, b):
        lo, hi = round(float(min(a, b)), 2), round(float(max(a, b)), 2)
        if self.w_mode.value == 'automatic':  # start from the automatic windows of both ramps
            self._from_auto(redraw=False)
        # a new window replaces the windows of this ramp it overlaps; otherwise it is added (more peaks)
        keep = [w for w in self.windows[ramp] if max(w) < lo or min(w) > hi]
        self.windows[ramp] = sorted(keep + [(hi, lo) if ramp == 'cooling' else (lo, hi)],
                                    key=lambda w: -max(w) if ramp == 'cooling' else min(w))
        self._silent(self.w_mode, 'semi-automatic')
        self._update()

    def _from_auto(self, redraw=True):
        res, _ = self._evaluate('automatic')
        self.windows = {'cooling': [], 'heating': []}
        for r, rr in res.results_by_ramp.items():
            self.windows[r] = [(round(float(pk.window[0]), 2), round(float(pk.window[1]), 2)) for pk in rr.peaks]
        if redraw:
            self._silent(self.w_mode, 'semi-automatic')
            self._update()

    def _clear(self, ramp):
        self.windows[ramp] = []
        self._update()

    def _save(self):
        mode = self.w_mode.value
        ev = {'mode': mode, 'cycle': self.w_cycle.value}
        if mode == 'semi-automatic':
            ev['windows'] = [{'ramp': r, 'T1': a, 'T2': b} for r, ws in self.windows.items() for a, b in ws]
            ev['windows_from_automatic'] = False
        self.w_msg.value = 'saving ...'
        self.w_msg.value = f'{self.run.name}: {self.run.save_evaluation(ev)}'
        self.w_info.value = f'&nbsp; stored mode: <b>{mode}</b>'

    def _folder_table(self):
        from nomad_dsc_trios.results_table import COLUMNS, fetch, write_csv  # noqa: PLC0415

        self.out_table.clear_output()
        tok, api = token(), find_api()
        if not tok:
            self.w_msg.value = 'Please log in to NOMAD first (user name and password at the top).'
            self.login_box.layout.display = None
            return
        if api is None:
            self.w_msg.value = '<span style="color:#b00">NOMAD API not reachable from Jupyter</span>'
            return
        root = upload_root(self.w_folder.value)
        folder = _posix(os.path.relpath(self.w_folder.value, root))
        try:
            rows = fetch(api, upload_id(root), {'Authorization': f'Bearer {tok}'}, '' if folder == '.' else folder)
        except Exception as e:
            self.w_msg.value = f'<span style="color:#b00">NOMAD API ({api}): {e}</span>'
            return
        path = os.path.join(self.w_folder.value, CSV_NAME)
        write_csv(rows, path)
        where = 'in the project' if in_north() else 'on this PC'
        self.w_msg.value = f'{len(rows)} DSC entries; saved as {_posix(os.path.relpath(path, root))} {where}'
        cols = ['entry_name', 'mode', 'cycle', 'Ms', 'Mf', 'As', 'Af', 'enthalpy_cooling', 'enthalpy_heating',
                'n_peaks_cooling', 'n_peaks_heating', 'flags']
        cols = [c for c in cols if c in COLUMNS]
        head = ''.join(f'<th>{c}</th>' for c in cols)
        body = ''.join('<tr>' + ''.join(f"<td>{'' if r[c] is None else r[c]}</td>" for c in cols) + '</tr>'
                       for r in rows)
        with self.out_table:
            from IPython.display import HTML, display  # noqa: PLC0415

            display(HTML(f'<table><tr>{head}</tr>{body}</table>'))

    # ---------------------------------------------------------------- drawing
    def _update(self):
        if self.run is None:
            return
        mode = self.w_mode.value
        try:
            res, exo_up = self._evaluate(mode)
        except Exception as e:  # show the problem instead of breaking the widget
            self.w_results.value = f'<span style="color:#b00">{type(e).__name__}: {e}</span>'
            return
        for ax, ramp in ((self.ax_c, 'cooling'), (self.ax_h, 'heating')):
            ax.clear()
            r = res.results_by_ramp.get(ramp)
            sign = 1.0 if (ramp == 'cooling') == exo_up else -1.0
            if r is None:  # semi-automatic without window: show the raw ramp to select on
                segs, _ = self.run.load()
                ramps, _ = EV.select_ramps(segs, self.w_cycle.value)
                if ramp in ramps:
                    T, q, _ = ramps[ramp]
                    ax.plot(T, q, color='#888888', lw=1)
            else:
                ax.plot(r.T, sign * r.y, color='#1f77b4' if ramp == 'cooling' else '#d62728', lw=1.5)
                a_, b_ = ('Ms', 'Mf') if ramp == 'cooling' else ('As', 'Af')
                for pk in r.peaks:
                    n = '' if len(r.peaks) == 1 else str(pk.index)
                    for e, lab, cur in ((pk.start, a_ + n, pk.window[0]), (pk.end, b_ + n, pk.window[1])):
                        ba, bb = e.baseline
                        ax.plot([cur, e.temperature], [sign * (ba * cur + bb), sign * (ba * e.temperature + bb)],
                                '--', color='#2ca02c', lw=1.5)
                        T0, y0 = e.tangent
                        xt = np.array([T0 + 0.8 * (T0 - e.temperature), e.temperature])
                        ax.plot(xt, sign * (y0 + e.slope * (xt - T0)), color='#333333', lw=1)
                        yy = sign * (ba * e.temperature + bb)
                        ax.plot([e.temperature], [yy], 'ko', ms=5)
                        ax.annotate(f'{lab} {e.temperature:.1f} °C', (e.temperature, yy), textcoords='offset points',
                                    xytext=(0, 8), ha='center', fontsize=8)
            for a, b in self.windows[ramp] if mode == 'semi-automatic' else []:
                ax.axvspan(min(a, b), max(a, b), color='#ff7f0e', alpha=0.12)
            ax.set_title(f'{ramp} (cycle {self.w_cycle.value}, {mode})', fontsize=10)
            ax.set_xlabel('Temperature (°C)')
            ax.set_ylabel(f"Heat flow (W/g, exo {'up' if exo_up else 'down'})")
        self.fig.tight_layout()
        self.fig.canvas.draw_idle()
        v = res.values
        cells = ' &nbsp; '.join(f'<b>{k}</b> {v[k]:.2f} °C' for k in ('Ms', 'Mf', 'As', 'Af') if k in v)
        enth = ' &nbsp; '.join(f'ΔH {k[9:]} {v[k]:.2f} J/g' for k in ('enthalpy_cooling', 'enthalpy_heating')
                               if k in v)
        msgs = '<br>'.join(res.messages)
        flags = '<br>'.join(f'{r} peak {pk.index}: {"; ".join(pk.flags)}'
                            for r, rr in res.results_by_ramp.items() for pk in rr.peaks if pk.flags)
        self.w_results.value = f'{cells or "no peak"} &nbsp; {enth}<br><small>{msgs}<br>{flags}</small>'
