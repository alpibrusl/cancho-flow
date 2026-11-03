/* The landing page's behaviour (docs/index.html): the human/agent switch, the agent view (docs/agents.md), the figures counting up, the sections arriving and the videos that play while
   they are on screen. Plain JavaScript; the page reads in full without it, and every animation is skipped under prefers-reduced-motion. Hand-written. */
(function () {
  var doc = document, body = doc.body, reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  doc.documentElement.classList.add("js");

  // the switch: human reads the page, agent reads agents.md as the bytes it is
  var bar = doc.querySelector("header.top .wrap"), pre = doc.getElementById("agent-full"), loaded = false;
  if (bar && pre) {
    var box = doc.createElement("div");
    box.className = "hright";
    box.innerHTML = '<span class="switch" role="group" aria-label="View this page as"><button type="button" id="view-human" aria-pressed="true">human</button><button type="button" id="view-agent" aria-pressed="false">agent</button></span>';
    bar.appendChild(box);
    var human = doc.getElementById("view-human"), agent = doc.getElementById("view-agent");
    var set = function (v, push) {
      body.setAttribute("data-view", v);
      human.setAttribute("aria-pressed", v === "human"); agent.setAttribute("aria-pressed", v === "agent");
      if (push && history.replaceState) { history.replaceState(null, "", v === "agent" ? "#agent" : location.pathname + location.search); }
      if (v === "agent") {
        scrollTo(0, 0);
        if (!loaded) { loaded = true; fetch("agents.md").then(function (r) { return r.ok ? r.text() : Promise.reject(); }).then(function (t) { pre.textContent = t; }, function () { loaded = false; pre.textContent = "agents.md could not be loaded here (a page opened as a file cannot fetch it). Open agents.md directly."; }); }
      }
    };
    human.addEventListener("click", function () { set("human", true); });
    agent.addEventListener("click", function () { set("agent", true); });
    if (location.hash === "#agent" || /[?&]view=agent/.test(location.search)) { set("agent", false); }
  }

  // sections arrive, figures count up, videos play while they are seen
  var io = "IntersectionObserver" in window ? new IntersectionObserver(function (es) {
    es.forEach(function (e) {
      var t = e.target;
      if (t.tagName === "VIDEO") { if (e.isIntersecting) { t.play().catch(function () {}); } else { t.pause(); } return; }
      if (!e.isIntersecting) { return; }
      io.unobserve(t);
      if (t.classList.contains("reveal")) { t.classList.add("in"); }
      t.querySelectorAll("b span[data-n]").forEach(count);
    });
  }, { threshold: 0.25 }) : null;
  function count(el) {
    var final = el.textContent, n = parseInt(final.replace(/,/g, ""), 10);
    if (reduce || !isFinite(n) || n < 20) { return; }
    var t0 = null;
    function step(t) {
      if (t0 === null) { t0 = t; }
      var k = Math.min(1, (t - t0) / 900), v = Math.round(n * (1 - Math.pow(1 - k, 3)));
      el.textContent = k < 1 ? v.toLocaleString("en-US") : final;
      if (k < 1) { requestAnimationFrame(step); }
    }
    requestAnimationFrame(step);
  }
  if (io) {
    doc.querySelectorAll(".reveal").forEach(function (el) { io.observe(el); });
    if (!reduce) { doc.querySelectorAll("video[data-autoplay]").forEach(function (v) { v.muted = true; io.observe(v); }); }
  } else { doc.querySelectorAll(".reveal").forEach(function (el) { el.classList.add("in"); }); }

  // opening the text of the runs plays them
  var logs = doc.querySelector("details.logs"), rp = doc.getElementById("replay");
  if (logs && rp) { logs.addEventListener("toggle", function () { if (logs.open) { rp.click(); } }); }

  // copy the build commands
  var cmds = doc.getElementById("build-cmds");
  if (cmds && navigator.clipboard) {
    var b = doc.createElement("button");
    b.type = "button"; b.className = "btn ghost"; b.textContent = "Copy the commands"; b.style.marginTop = ".8rem";
    b.addEventListener("click", function () { navigator.clipboard.writeText(cmds.textContent).then(function () { b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy the commands"; }, 1800); }); });
    cmds.parentNode.insertBefore(b, cmds.nextSibling);
  }
})();
