const keys = ['demo_market', 'market_family', 'market_level', 'market_format', 'market_q', 'market_offset']

export function initialWorkspaceTab(fallback: string) {
  return new URLSearchParams(location.search).has('demo_market') ? 'market' : fallback
}

export function leaveMarket() {
  const url = new URL(location.href)
  keys.forEach(key => url.searchParams.delete(key))
  history.replaceState(null, '', url)
}
