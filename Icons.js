.pragma library

// Only bundled assets may be loaded; account labels/IDs must never become URLs.
function iconKey(view, harnessId, aiName) {
  if (view === "harness") {
    if (harnessId === "opencode" || harnessId === "codex") return harnessId
    return ""
  }
  var brands = { "ChatGPT": "codex", "Claude": "claude", "DeepSeek": "deepseek", "ZAI": "zai" }
  return Object.prototype.hasOwnProperty.call(brands, aiName) ? brands[aiName] : ""
}

function candidates(key, lightSurface) {
  if (["opencode", "codex", "claude", "deepseek", "zai"].indexOf(key) < 0) return []
  var paths = []
  if (lightSurface && ["opencode", "codex", "zai"].indexOf(key) >= 0)
    paths.push("assets/" + key + "-light.svg")
  paths.push("assets/" + key + ".svg")
  return paths
}

function channelLuminance(value) {
  return value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4)
}

function lightSurface(r, g, b) {
  return 0.2126 * channelLuminance(r) + 0.7152 * channelLuminance(g) + 0.0722 * channelLuminance(b) >= 0.5
}
