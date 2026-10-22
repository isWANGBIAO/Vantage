export function canToggleWithSpace(event, modalOpen) {
  const target = event.target;
  return (
    (event.code === "Space" || event.key === " ") &&
    !event.repeat &&
    !event.isComposing &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey &&
    !modalOpen &&
    !event.view?.getSelection?.()?.toString() &&
    !target?.isContentEditable &&
    !["INPUT", "TEXTAREA", "SELECT", "BUTTON", "A"].includes(target?.tagName) &&
    !target?.closest?.(
      '[contenteditable="true"], [role="dialog"], [role="textbox"], [data-live-output]',
    )
  );
}
export function reconcileDraft(local, external) {
  if (external.version === local.version) return null;
  if (local.text !== local.base && local.text !== external.text)
    return { conflict: true, text: local.text, external };
  return { conflict: false, text: external.text, version: external.version };
}
export function publicationStatus(local, project) {
  if (local.text !== local.base) return "未保存";
  if (!local.text.trim()) return "目标为空，无法运行";
  return local.version && local.version === project.adoptedGoalVersion
    ? "当前执行已采用"
    : "已保存，下次执行采用";
}
export function projectScopeKey(project) {
  return project ? JSON.stringify([project.id, project.root]) : null;
}
