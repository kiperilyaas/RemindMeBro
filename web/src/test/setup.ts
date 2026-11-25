import "@testing-library/jest-dom/vitest";
// jsdom has no layout: scrolling is a no-op in tests
Element.prototype.scrollIntoView = function scrollIntoView() {};
window.scrollTo = () => {};
// jsdom cannot play media: play() rejects like a browser that blocks the video
HTMLMediaElement.prototype.play = function play() { return Promise.reject(new Error("no media in jsdom")); };
HTMLMediaElement.prototype.pause = function pause() {};
