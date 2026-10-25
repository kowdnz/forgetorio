// Apresentação de 24 segundos. Sem bibliotecas, áudio ou requisições externas.
const DURATION = 24_000;
const SCENE_STARTS = [0, 4_000, 9_000, 14_000, 19_000];

const player = document.querySelector(".player");
const scenes = [...document.querySelectorAll(".scene")];
const counter = document.querySelector("#counter");
const progress = document.querySelector("#progress");
const timeline = document.querySelector("#timeline");
const toggle = document.querySelector("#toggle");
const replay = document.querySelector("#replay");

let elapsed = 0;
let paused = false;
let currentScene = -1;
let lastFrame = 0;

function clock(ms) {
  return `00:${String(Math.floor(ms / 1000)).padStart(2, "0")}`;
}

function setScene(index) {
  if (index === currentScene) return;
  currentScene = index;
  scenes.forEach((scene, i) => {
    scene.classList.toggle("active", i === index);
    scene.setAttribute("aria-hidden", String(i !== index));
  });
}

function render() {
  const index = SCENE_STARTS.reduce((found, start, i) => elapsed >= start ? i : found, 0);
  setScene(index);
  counter.textContent = `${clock(elapsed)} / 00:24`;
  progress.style.width = `${elapsed / DURATION * 100}%`;
  timeline.setAttribute("aria-valuenow", String(Math.round(elapsed / 1000)));
  timeline.setAttribute("aria-valuetext", `${clock(elapsed)} de 00:24`);
  player.classList.toggle("paused", paused);
  toggle.innerHTML = elapsed >= DURATION ? "↺ <span>Rever</span>" : paused ? "▶ <span>Continuar</span>" : "Ⅱ <span>Pausar</span>";
  toggle.setAttribute("aria-label", elapsed >= DURATION ? "Rever apresentação" : paused ? "Continuar apresentação" : "Pausar apresentação");
}

function seek(ms) {
  elapsed = Math.max(0, Math.min(DURATION, ms));
  if (elapsed >= DURATION) paused = true;
  render();
}

function frame(stamp) {
  if (lastFrame && !paused && !document.hidden) {
    elapsed = Math.min(DURATION, elapsed + stamp - lastFrame);
    if (elapsed >= DURATION) paused = true;
    render();
  }
  lastFrame = stamp;
  requestAnimationFrame(frame);
}

toggle.addEventListener("click", () => {
  if (elapsed >= DURATION) {
    elapsed = 0;
    paused = false;
  } else {
    paused = !paused;
  }
  render();
});

replay.addEventListener("click", () => {
  elapsed = 0;
  paused = false;
  render();
});

timeline.addEventListener("click", event => {
  const track = timeline.querySelector(".timeline-track");
  const rect = track.getBoundingClientRect();
  seek((event.clientX - rect.left) / rect.width * DURATION);
});

timeline.addEventListener("keydown", event => {
  if (event.key === "ArrowRight") seek(elapsed + 1000);
  else if (event.key === "ArrowLeft") seek(elapsed - 1000);
  else if (event.key === "Home") seek(0);
  else if (event.key === "End") seek(DURATION);
  else return;
  event.preventDefault();
});

document.addEventListener("visibilitychange", () => { lastFrame = 0; });
document.addEventListener("keydown", event => {
  if (event.target instanceof HTMLElement && event.target.closest("button, [role='slider']")) return;
  if (event.code === "Space") {
    event.preventDefault();
    toggle.click();
  } else if (event.key.toLowerCase() === "r") {
    replay.click();
  }
});

render();
requestAnimationFrame(frame);
