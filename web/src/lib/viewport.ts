// Some phone browsers (Chrome and Edge on iPhone) draw the page under their own bottom toolbar, so a bar
// fixed at bottom: 0 ends up half hidden. This measures how much of the fixed area the visible viewport
// does not show at the bottom and exposes it as --screen-bottom (px), which the mobile tab bar adds to its
// offset. An on-screen keyboard also shrinks the visible viewport: large values are ignored, so the tab bar
// stays put while typing.
const KEYBOARD_PX = 140;

export function trackScreenBottom(): () => void {
  const vv = window.visualViewport;
  if (!vv) return () => undefined;
  const probe = document.createElement("div");
  probe.setAttribute("aria-hidden", "true");
  probe.style.cssText = "position:fixed;top:0;bottom:0;left:0;width:0;visibility:hidden;pointer-events:none";
  document.body.appendChild(probe);
  let last = -1;
  const update = () => {
    const fixedBottom = probe.getBoundingClientRect().bottom;
    const hidden = Math.round(fixedBottom - (vv.offsetTop + vv.height));
    const px = hidden > 0 && hidden < KEYBOARD_PX ? hidden : 0;
    if (px !== last) { last = px; document.documentElement.style.setProperty("--screen-bottom", `${px}px`); }
  };
  update();
  vv.addEventListener("resize", update);
  vv.addEventListener("scroll", update);
  window.addEventListener("orientationchange", update);
  return () => {
    vv.removeEventListener("resize", update); vv.removeEventListener("scroll", update);
    window.removeEventListener("orientationchange", update); probe.remove();
  };
}
