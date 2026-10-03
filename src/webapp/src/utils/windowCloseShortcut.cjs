function handleWindowCloseShortcut(event, input, window, platform = process.platform) {
  const modifier = platform === 'darwin' ? input.meta && !input.control : input.control && !input.meta;
  if (input.type !== 'keyDown' || String(input.key).toLowerCase() !== 'w'
    || !modifier || input.alt || input.shift || input.isAutoRepeat) return false;
  event.preventDefault();
  // Use the existing close handler: hide to tray, unless an explicit quit is underway.
  window.close();
  return true;
}

module.exports = { handleWindowCloseShortcut };
