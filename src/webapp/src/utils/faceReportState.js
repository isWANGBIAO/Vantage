export function getFaceReportState(payload) {
  if (!payload) {
    return {
      status: 'empty',
      data: null,
      error: null,
    };
  }

  if (payload.error === 'No report generated') {
    return {
      status: 'empty',
      data: null,
      error: null,
    };
  }

  if (payload.error) {
    return {
      status: 'error',
      data: null,
      error: payload.error,
    };
  }

  return {
    status: 'ready',
    data: payload,
    error: null,
  };
}
