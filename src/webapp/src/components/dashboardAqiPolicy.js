export function shouldUseDashboardGeolocation({ isVisible, permissionState }) {
  if (permissionState === 'granted') {
    return true;
  }

  return Boolean(isVisible);
}
