import { useEffect, useRef, useState } from 'react';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';
import { fetchBackend } from '../utils/backendRequest.js';
import { clothingCanSubmit, clothingDraft, clothingErrorKind, clothingEvidenceNotice, clothingNumber, clothingPayload, editClothingDraft, emptyClothingDraft, newClothingCandidate } from '../utils/clothingFit.js';
import './ClothingFit.css';

const COPY = {
  zh: {
    title: '衣服尺码与试穿比较', intro: '从尺码截图出发，用具体款式的历史试穿证据比较，不给品牌统一贴 M / L 标签。',
    source: '唯一数据源', path: 'Excel文件路径', pathHint: '留空使用自动发现的衣服尺寸.xlsx；路径保存在统一设置JSON，记录仅保存在该Excel。', savePath: '保存路径', refresh: '刷新历史（保留草稿）', resolved: '当前工作簿',
    image: '1 · 尺码截图', imageHint: '可选择或粘贴PNG / JPEG / WEBP截图。只有点击“提取尺码”才会把图片发送给当前选中的AI服务和模型，不切换备用服务；历史比较在本地完成。', upload: '选择尺码截图', extract: '提取尺码', clearImage: '清除图片', model: '当前读图AI', noVision: '尚未配置可用的读图AI，可先手动填写，或到现有AI设置中选择支持图片输入的模型。', preview: '待提取的尺码截图（未发送）', extraction: '提取结果（请选择一行校对）', vision_failed: '当前AI读图未完成。请检查模型是否支持图片输入，也可手动录入；没有切换服务或修改原表。',
    editor: '2 · 校对尺码与试穿反馈', new: '新建空白记录', copy: '复制尺寸为新候选（不复制试穿反馈）', editing: '正在查看历史第{row}行：原尺寸只读，仅可更新试穿反馈；如需修改尺寸，请复制为新候选。',
    garment: '衣服/具体款式', brand: '品牌', style_code: '款号', category: '类别', size: '尺码（保存必填；不清楚填未知）', component: '尺寸属于哪个部件',
    length_cm: '衣长 cm', chest_cm: '胸围 cm（整圈）', chest_width_cm: '平铺胸宽 cm（半围）', shoulder_cm: '肩宽 cm', sleeve_cm: '袖长 cm', measurement_tolerance_cm: '允许测量误差 ±cm', length_basis: '衣长测量口径', sleeve_basis: '袖长测量口径', measurement_source: '尺寸来源',
    feedback: '试穿反馈（与截图尺寸分开）', trial_date: '试穿日期', feedback_scope: '反馈针对哪个部件', shoulder_feedback: '肩部外观感受', sleeve_feedback: '袖长感受', length_feedback: '衣长感受', chest_feedback: '胸部松紧感受', mobility_feedback: '抬手/活动是否受限', overall_feedback: '最终结论/总体感受', layering: '内搭/试穿方式', notes: '来源与备注',
    unknown: '未说明就留空，不由AI补全', precision: '胸围与半围不能混填；肩部“显窄”不等于“紧”或“活动受限”。未知测量口径请保持未知。',
    reviewed: '我已核对当前尺码、单位、部件和反馈范围', compare: '与历史记录比较', append: '追加到Excel', update: '仅更新本行试穿反馈', cancel: '取消等待', loading: '处理中…',
    history: '3 · 历史试穿记录', noHistory: '暂无可读取的历史衣服记录。', row: '行', date: '试穿日期', select: '查看/补充反馈', original: '查看原始记录、来源和警告', noFeedback: '尚无明确试穿结论', body: '非衣服数据，仅保留查看',
    result: '比较结果', noMatches: '没有足够同口径的可比记录，不能推断尺码合适。', difference: '新衣服 − 历史记录', field: '项目', candidate: '新尺码', historical: '历史尺寸', delta: '差值 cm', tolerance: '在已知误差范围内', toleranceUnknown: '误差未知', suitable: '有同范围合适证据', reference: '仅供尺寸参照', unknowns: '仍不清楚', warnings: '注意', disclaimer: '尺寸接近不代表穿着一定合适；版型、弹性、内搭与测量误差仍可能影响体验。', staleHistorical: '原工作簿版本已变化。为避免错写行或覆盖他人反馈，请重新选择最新历史行；当前草稿保留，也可复制为新候选。',
    loaded: '历史已刷新；草稿仍保留，请重新核对后比较或保存。', saved: '已保存到原Excel并验证工作簿。', pathSaved: '数据源路径已保存；未保存的草稿仍保留，请重新核对。', extracted: '已提取，尚未保存。请逐行检查，尤其是整圈胸围、半围和部件。',
    uncertain: '写入结果尚未确认。请先刷新并查看历史，勿重复追加；草稿已保留。', cancelled: '已取消等待，草稿保留。', conflict: 'Excel被占用或原文件已更新。请保存并关闭Excel，再刷新核对后重试；本地输入已保留。', invalid: '请检查输入：数字须为有效cm数值、衣服名称不可为空；请勿把未知填成0。', image_large: '截图超过8MB，请缩小后再选择。', unavailable: '当前数据源或视觉服务不可用。请检查文件路径和图片服务设置，草稿已保留。', failed: '操作未完成，草稿已保留。请检查本地配置后重试。',
    discard: '切换会替换当前未保存草稿。', keep: '保留当前草稿', replace: '放弃草稿并切换',
  },
  en: {
    title: 'Clothing sizes & fitting evidence', intro: 'Compare a size chart with specific historical fittings, not a universal M/L rule for a brand.',
    source: 'Single source', path: 'Excel workbook path', pathHint: 'Leave blank to discover 衣服尺寸.xlsx. The path uses shared JSON settings; records stay only in this workbook.', savePath: 'Save path', refresh: 'Refresh history (keep draft)', resolved: 'Current workbook',
    image: '1 · Size-chart screenshot', imageHint: 'Choose or paste a PNG / JPEG / WEBP. Only Extract sends the image to the currently selected AI provider/model, without fallback. Historical comparisons run locally.', upload: 'Choose size chart', extract: 'Extract sizes', clearImage: 'Clear image', model: 'Current reading AI', noVision: 'No reading AI is configured. Enter sizes manually or select an image-capable model in existing AI settings.', preview: 'Size-chart preview (not sent)', extraction: 'Extracted rows — select one to review', vision_failed: 'The selected AI did not finish reading the chart. Check image-input support or enter sizes manually. No fallback or workbook change occurred.',
    editor: '2 · Review sizes & fitting feedback', new: 'New blank record', copy: 'Copy dimensions to new candidate (clear feedback)', editing: 'Historical row {row}: dimensions are read-only; update fitting feedback only. Copy to a new candidate to correct dimensions.',
    garment: 'Garment / specific style', brand: 'Brand', style_code: 'Style code', category: 'Category', size: 'Size (required to save; unknown is allowed)', component: 'Measured component', length_cm: 'Length cm', chest_cm: 'Chest circumference cm', chest_width_cm: 'Flat chest width cm (half)', shoulder_cm: 'Shoulder cm', sleeve_cm: 'Sleeve cm', measurement_tolerance_cm: 'Measurement tolerance ±cm', length_basis: 'Length convention', sleeve_basis: 'Sleeve convention', measurement_source: 'Dimension source',
    feedback: 'Fitting feedback — separate from chart dimensions', trial_date: 'Fitting date', feedback_scope: 'Feedback scope', shoulder_feedback: 'Shoulder appearance', sleeve_feedback: 'Sleeve-length feedback', length_feedback: 'Length feedback', chest_feedback: 'Chest fit', mobility_feedback: 'Movement restriction', overall_feedback: 'Final / overall conclusion', layering: 'Layering / fitting method', notes: 'Source & notes', unknown: 'Leave unspecified information blank; AI must not invent it.', precision: 'Do not confuse circumference with flat width, or narrow-looking shoulders with tightness or restricted movement. Keep unknown conventions unknown.',
    reviewed: 'I have checked sizes, units, components and feedback scope', compare: 'Compare with history', append: 'Append to Excel', update: 'Update feedback on this row only', cancel: 'Cancel waiting', loading: 'Working…', history: '3 · Historical fittings', noHistory: 'No clothing history could be read.', row: 'Row', date: 'Fitting date', select: 'View / add feedback', original: 'Original record, source & warnings', noFeedback: 'No explicit fitting conclusion', body: 'Not a garment — view only',
    result: 'Comparison', noMatches: 'There are not enough comparable records to infer fit.', difference: 'New garment − historical record', field: 'Measurement', candidate: 'New', historical: 'Historical', delta: 'Difference cm', tolerance: 'Within known tolerance', toleranceUnknown: 'Unknown tolerance', suitable: 'Suitable fitting evidence for this scope', reference: 'Dimensions only', unknowns: 'Still unknown', warnings: 'Cautions', disclaimer: 'Similar dimensions do not guarantee fit. Cut, stretch, layering and measurement error can still matter.', staleHistorical: 'The workbook version changed. Reselect the latest historical row before writing feedback, to avoid targeting the wrong row or overwriting another edit. Your draft was kept; you can also copy it to a new candidate.',
    loaded: 'History refreshed. Your draft was kept; review it again before comparing or saving.', saved: 'Saved to the source Excel; workbook validated.', pathSaved: 'Source path saved. Your draft was kept; review it again.', extracted: 'Extracted, not saved. Review every row, particularly circumference, flat width and components.', uncertain: 'Write outcome is unconfirmed. Refresh and inspect history before retrying to avoid a duplicate. Your draft was kept.', cancelled: 'Waiting cancelled; draft kept.', conflict: 'Excel is open or the source changed. Save and close Excel, then refresh and review. Your draft was kept.', invalid: 'Check the inputs: use valid cm numbers and a garment name. Do not replace unknowns with zero.', image_large: 'Image exceeds 8MB. Resize it first.', unavailable: 'Source or vision service unavailable. Check workbook path and Image Provider settings. Draft kept.', failed: 'The operation did not finish. Draft kept; check local settings and retry.', discard: 'Switching will replace your unsaved draft.', keep: 'Keep draft', replace: 'Discard draft and switch',
  },
};
const PARTS = ['未知', '整件', '外壳', '内胆'];
const PART_NAMES = { 未知: 'Unknown', 整件: 'Whole garment', 外壳: 'Shell', 内胆: 'Liner' };
const DIMENSIONS = ['length_cm', 'chest_cm', 'chest_width_cm', 'shoulder_cm', 'sleeve_cm', 'measurement_tolerance_cm'];
const IDENTITY = ['garment', 'brand', 'style_code', 'category', 'size'];
const FEEDBACK = ['shoulder_feedback', 'sleeve_feedback', 'length_feedback', 'chest_feedback', 'mobility_feedback', 'overall_feedback', 'layering', 'notes'];

const ENDPOINTS = Object.freeze({ state: '/api/v1/clothing/state', config: '/api/v1/clothing/config',
  extract: '/api/v1/clothing/extract', compare: '/api/v1/clothing/compare', records: '/api/v1/clothing/records' });
async function request(path, body, signal, method = 'POST') {
  if (!ENDPOINTS[path]) throw new TypeError('Unknown clothing operation');
  const response = await fetchBackend(ENDPOINTS[path], {
    method: body === undefined ? 'GET' : method, signal, retryPolicy: 'none', allowHttpError: true,
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    // Drain even safe errors so the app-protocol transport closes after a 409.
    // Do not surface raw server payloads (which may contain private file data).
    await response.arrayBuffer();
    const error = new Error('Clothing request failed'); error.status = response.status; throw error;
  }
  return response.json();
}
function List({ values, label }) {
  return Array.isArray(values) && values.length ? <div className="clothing-notes"><strong>{label}</strong><ul>{values.map((value, index) => <li key={index}>{String(value)}</li>)}</ul></div> : null;
}

export default function ClothingFit() {
  const { effectiveLanguage } = useDisplayLanguage();
  const english = String(effectiveLanguage).startsWith('en');
  const c = COPY[english ? 'en' : 'zh'];
  const [source, setSource] = useState(null);
  const [path, setPath] = useState('');
  const [view, setView] = useState(() => ({ draft: emptyClothingDraft(), confirmed: false, dirty: false, comparison: null }));
  const [image, setImage] = useState(null);
  const [extractions, setExtractions] = useState([]);
  const [extractWarnings, setExtractWarnings] = useState([]);
  const [busy, setBusy] = useState('load');
  const [failure, setFailure] = useState(null);
  const [notice, setNotice] = useState(null);
  const [uncertain, setUncertain] = useState(false);
  const [staleHistorical, setStaleHistorical] = useState(false);
  const [pendingDraft, setPendingDraft] = useState(null);
  const active = useRef(null);
  const mounted = useRef(false);
  const imageSequence = useRef(0);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController(); active.current = controller;
    request('state', undefined, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      setSource(value); setPath(value.configured_path || '');
    }).catch(error => { if (!controller.signal.aborted) setFailure(clothingErrorKind(error)); })
      .finally(() => { if (active.current === controller) { active.current = null; if (mounted.current) setBusy(''); } });
    return () => { mounted.current = false; active.current?.abort(); };
  }, []);

  async function perform(kind, action) {
    if (active.current) return;
    const controller = new AbortController(); active.current = controller;
    setBusy(kind); setFailure(null); setNotice(null);
    try { await action(controller.signal); }
    catch (error) {
      if (!mounted.current) return;
      const errorKind = clothingErrorKind(error); setFailure(kind === 'extract' && errorKind !== 'cancelled' ? 'vision_failed' : errorKind);
      setView(previous => ({ ...previous, confirmed: false }));
      if (['save', 'feedback', 'config'].includes(kind) && (!error.status || error.status >= 500)) { setUncertain(true); setNotice('uncertain'); }
    } finally {
      if (active.current === controller) { active.current = null; if (mounted.current) setBusy(''); }
    }
  }
  function update(key, value) { setView(previous => editClothingDraft(previous, key, value)); setNotice(null); }
  function adopt(record) {
    const next = clothingDraft(record);
    if (view.dirty) { setPendingDraft(next); return; }
    setStaleHistorical(false);
    setView({ draft: next, confirmed: false, dirty: false, comparison: null });
  }
  async function refresh(signal) {
    const value = await request('state', undefined, signal); if (signal.aborted) return;
    if (Number.isInteger(view.draft.row) && source?.revision !== value.revision) setStaleHistorical(true);
    setSource(value); setUncertain(false); setView(previous => ({ ...previous, confirmed: false, comparison: null }));
    setFailure(value.error ? 'unavailable' : null); setNotice(value.error ? null : 'loaded');
  }
  function chooseImage(file) {
    if (!file || busy) return;
    setFailure(null);
    if (file.size > 8 * 1024 * 1024) { setFailure('image_large'); return; }
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) { setFailure('invalid'); return; }
    const sequence = ++imageSequence.current;
    setImage(null); setExtractions([]); setExtractWarnings([]);
    const reader = new FileReader();
    reader.onload = () => { if (mounted.current && imageSequence.current === sequence) { setImage(String(reader.result)); setExtractions([]); setExtractWarnings([]); } };
    reader.onerror = () => { if (mounted.current && imageSequence.current === sequence) setFailure('failed'); };
    reader.readAsDataURL(file);
  }
  function paste(event) {
    const file = Array.from(event.clipboardData?.items || []).find(item => item.kind === 'file' && item.type.startsWith('image/'))?.getAsFile();
    if (file) { event.preventDefault(); chooseImage(file); }
  }
  async function save(signal, feedbackOnly) {
    const record = clothingPayload(view.draft);
    const value = await request('records', { records: [record], expected_revision: source.revision, confirmed: true }, signal);
    if (signal.aborted) return;
    setSource(value); setView(previous => ({ ...previous, confirmed: false, dirty: false, comparison: null,
      draft: feedbackOnly ? previous.draft : emptyClothingDraft() })); setNotice('saved');
  }
  const historical = Number.isInteger(view.draft.row);
  const canSubmit = clothingCanSubmit(view.draft, view.confirmed, source?.revision, busy, uncertain || staleHistorical);
  const evidenceNotice = clothingEvidenceNotice(view.draft, english);
  const records = Array.isArray(source?.records) ? source.records : [];
  const choices = (values) => values.map(value => <option value={value} key={value}>{english ? PART_NAMES[value] || ({ 后肩衣长: 'Back shoulder length', 肩点袖长: 'Shoulder-seam sleeve', 连肩袖长: 'Raglan / neck-to-cuff sleeve' }[value]) || value : value}</option>);
  const field = (key, type = 'text', readOnly = false) => <label key={key}>{c[key]}<input name={key} type={type} value={view.draft[key] ?? ''} disabled={Boolean(busy)} readOnly={readOnly}
    inputMode={DIMENSIONS.includes(key) ? 'decimal' : undefined} onChange={event => update(key, event.target.value)} /></label>;

  return <section className="clothing-fit" aria-labelledby="clothing-fit-title" onPaste={paste}>
    <header><h1 id="clothing-fit-title">{c.title}</h1><p>{c.intro}</p></header>
    <section className="clothing-panel" aria-label={c.source}>
      <h2>{c.source}</h2><label>{c.path}<input name="workbook_path" value={path} disabled={Boolean(busy)} onChange={event => setPath(event.target.value)} /></label>
      <p className="clothing-muted">{c.pathHint}</p><div className="clothing-actions">
        <button disabled={Boolean(busy) || uncertain} onClick={() => void perform('config', async signal => {
          const value = await request('config', { workbook_path: path.trim() }, signal, 'PUT'); if (signal.aborted) return;
          if (Number.isInteger(view.draft.row)) setStaleHistorical(true);
          setSource(value); setPath(value.configured_path || ''); setView(previous => ({ ...previous, confirmed: false, comparison: null })); setNotice('pathSaved');
        })}>{c.savePath}</button>
        <button disabled={Boolean(busy)} onClick={() => void perform('refresh', refresh)}>{c.refresh}</button>
      </div><p className="clothing-path">{c.resolved}: {source?.workbook_path || '—'}</p>
      {source?.error ? <p role="alert">{c.unavailable}</p> : null}<List values={source?.warnings} label={c.warnings} />
    </section>
    <div className="clothing-status" aria-live="polite">{busy ? <><span>{c.loading}</span><button onClick={() => active.current?.abort()}>{c.cancel}</button></> : null}
      {failure ? <p role="alert">{c[failure] || c.failed}</p> : null}{notice ? <p>{c[notice]}</p> : null}</div>
    {pendingDraft ? <div className="clothing-panel clothing-confirm" role="alertdialog" aria-label={c.discard}><p>{c.discard}</p>
      <div className="clothing-actions"><button onClick={() => setPendingDraft(null)}>{c.keep}</button><button onClick={() => { setView({ draft: pendingDraft, confirmed: false, dirty: false, comparison: null }); setStaleHistorical(false); setPendingDraft(null); }}>{c.replace}</button></div></div> : null}
    <section className="clothing-panel" aria-label={c.image}>
      <h2>{c.image}</h2><p>{c.imageHint}</p><p>{c.model}: {[source?.vision?.provider_route, source?.vision?.model].filter(Boolean).join(' / ') || '—'}</p>
      {!source?.vision?.ready ? <p className="clothing-muted">{c.noVision}</p> : null}
      {source?.vision?.warning ? <p className="clothing-muted">{source.vision.warning}</p> : null}
      <label className="clothing-upload">{c.upload}<input type="file" accept="image/png,image/jpeg,image/webp" disabled={Boolean(busy)} onChange={event => { chooseImage(event.target.files?.[0]); event.target.value = ''; }} /></label>
      {image ? <div className="clothing-image"><img src={image} alt={c.preview} /><div className="clothing-actions">
        <button disabled={Boolean(busy) || !source?.vision?.ready} onClick={() => void perform('extract', async signal => {
          const sequence = imageSequence.current;
          const value = await request('extract', { image_data_url: image, provider_route: source.vision.provider_route, model: source.vision.model }, signal);
          if (signal.aborted || sequence !== imageSequence.current) return;
          setExtractions(Array.isArray(value.records) ? value.records : []); setExtractWarnings(value.warnings || []); setNotice('extracted');
        })}>{c.extract}</button><button disabled={Boolean(busy)} onClick={() => { imageSequence.current++; setImage(null); setExtractions([]); setExtractWarnings([]); }}>{c.clearImage}</button>
      </div></div> : null}
      {extractions.length ? <fieldset className="clothing-extractions"><legend>{c.extraction}</legend>{extractions.map((record, index) => <button key={index} disabled={Boolean(busy)} onClick={() => adopt({ ...record, row: null })}>
        {index + 1}. {[record.brand, record.garment, record.size, record.component].filter(Boolean).join(' · ')}
      </button>)}</fieldset> : null}<List values={extractWarnings} label={c.warnings} />
    </section>
    <section className="clothing-panel clothing-editor" aria-label={c.editor}>
      <div className="clothing-section-heading"><h2>{c.editor}</h2><button disabled={Boolean(busy)} onClick={() => adopt(emptyClothingDraft())}>{c.new}</button></div>
      {historical ? <><p className="clothing-muted">{c.editing.replace('{row}', view.draft.row)}</p><button disabled={Boolean(busy)} onClick={() => adopt(newClothingCandidate(view.draft))}>{c.copy}</button></> : null}
      {staleHistorical ? <p role="alert">{c.staleHistorical}</p> : null}
      <div className="clothing-grid">{IDENTITY.map(key => field(key, 'text', historical))}
        <label>{c.component}<select name="component" value={view.draft.component} disabled={Boolean(busy) || historical} onChange={event => update('component', event.target.value)}>{choices(PARTS)}</select></label>
        {DIMENSIONS.map(key => field(key, 'text', historical))}
        <label>{c.length_basis}<select name="length_basis" value={view.draft.length_basis} disabled={Boolean(busy) || historical} onChange={event => update('length_basis', event.target.value)}>{choices(['未知', '后肩衣长'])}</select></label>
        <label>{c.sleeve_basis}<select name="sleeve_basis" value={view.draft.sleeve_basis} disabled={Boolean(busy) || historical} onChange={event => update('sleeve_basis', event.target.value)}>{choices(['未知', '肩点袖长', '连肩袖长'])}</select></label>
        {field('measurement_source', 'text', historical)}
      </div><p className="clothing-muted">{c.precision}</p><List values={view.draft.warnings} label={c.warnings} />
      <fieldset><legend>{c.feedback}</legend><div className="clothing-grid">{field('trial_date', 'date')}
        <label>{c.feedback_scope}<select name="feedback_scope" value={view.draft.feedback_scope} disabled={Boolean(busy)} onChange={event => update('feedback_scope', event.target.value)}>{choices(PARTS)}</select></label>
        {FEEDBACK.map(key => <label key={key}>{c[key]}<textarea name={key} rows={2} placeholder={c.unknown} value={view.draft[key] || ''} disabled={Boolean(busy)} onChange={event => update(key, event.target.value)} /></label>)}
      </div></fieldset>{evidenceNotice ? <p className="clothing-muted">{evidenceNotice}</p> : null}
      <label className="clothing-reviewed"><input type="checkbox" name="clothing_reviewed" checked={view.confirmed} disabled={Boolean(busy) || uncertain} onChange={event => setView(previous => ({ ...previous, confirmed: event.target.checked }))} />{c.reviewed}</label>
      <div className="clothing-actions"><button disabled={!canSubmit} onClick={() => void perform('compare', async signal => {
        const value = await request('compare', { candidate: clothingPayload(view.draft), confirmed: true, revision: source.revision }, signal); if (!signal.aborted) setView(previous => ({ ...previous, comparison: value }));
      })}>{c.compare}</button><button disabled={!canSubmit || historical || !view.draft.size.trim()} onClick={() => void perform('save', signal => save(signal, false))}>{c.append}</button>
        <button disabled={!canSubmit || !historical} onClick={() => void perform('feedback', signal => save(signal, true))}>{c.update}</button></div>
    </section>
    {view.comparison ? <section className="clothing-panel clothing-result" aria-label={c.result}><h2>{c.result}</h2><p>{view.comparison.summary}</p><p className="clothing-muted">{c.disclaimer}</p>
      <List values={view.comparison.unknowns} label={c.unknowns} /><List values={view.comparison.warnings} label={c.warnings} />
      {!view.comparison.matches?.length ? <p>{c.noMatches}</p> : null}
      {(view.comparison.matches || []).map((match, index) => <article key={`${match.row}-${index}`} className="clothing-match">
        <h3>{[match.brand, match.garment, match.style_code, match.size, match.component].filter(Boolean).join(' · ')}</h3><p>{c.row} {match.row} · {match.known_suitable ? c.suitable : c.reference}</p><p>{c.difference}</p>
        <div className="clothing-table-wrap"><table><thead><tr><th>{c.field}</th><th>{c.candidate}</th><th>{c.historical}</th><th>{c.delta}</th><th>{c.tolerance}</th></tr></thead>
          <tbody>{(match.differences || []).map((difference, number) => <tr key={number}><td>{c[difference.field] || difference.label || difference.field}</td><td>{clothingNumber(difference.candidate_cm)}</td><td>{clothingNumber(difference.history_cm)}</td><td>{difference.delta_cm > 0 ? '+' : ''}{clothingNumber(difference.delta_cm)}</td><td>{difference.tolerance_known !== true ? c.toleranceUnknown : difference.within_tolerance === true ? (english ? 'Yes' : '是') : (english ? 'No' : '否')}</td></tr>)}</tbody></table></div>
        <List values={match.feedback} label={c.feedback} /><List values={match.warnings} label={c.warnings} />
      </article>)}
    </section> : null}
    <section className="clothing-panel" aria-label={c.history}><h2>{c.history}</h2>{!records.length ? <p>{source?.error ? c.unavailable : c.noHistory}</p> : <div className="clothing-table-wrap"><table className="clothing-history"><thead><tr><th>{c.row}</th><th>{c.garment}</th><th>{c.size}</th><th>{c.component}</th><th>{c.date}</th><th>{c.overall_feedback}</th><th>{c.original}</th></tr></thead>
      <tbody>{records.map((record, index) => <tr key={record.row || index}><td>{record.row}</td><td>{[record.brand, record.garment, record.style_code].filter(Boolean).join(' · ') || '—'}</td><td>{record.size || '—'}</td><td>{record.component || '—'}</td><td>{record.trial_date || '—'}</td><td>{record.overall_feedback || c.noFeedback}</td><td>
        {record.record_kind === 'garment' ? <button disabled={Boolean(busy)} onClick={() => adopt(record)}>{c.select}</button> : <span>{c.body}</span>}
        <details><summary>{c.original}</summary><p>{record.notes}</p><p>{clothingEvidenceNotice(record, english)}</p><List values={record.warnings} label={c.warnings} /><pre>{JSON.stringify(record.raw_fields || record, null, 2)}</pre></details>
      </td></tr>)}</tbody></table></div>}</section>
  </section>;
}
