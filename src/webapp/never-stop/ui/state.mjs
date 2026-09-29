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
export function publicationStatus(text, project) {
  if (text !== project.publishedGoal) return "草稿未发布";
  return project.publishedRevision &&
    project.publishedRevision === project.adoptedRevision
    ? "当前执行已采用"
    : "已发布，等待采用";
}
export function projectScopeKey(project) {
  return project ? JSON.stringify([project.id, project.root]) : null;
}
