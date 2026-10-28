/* Shared navigation and account controls for all admin pages. */
(function () {
  const NAV = [
    { href: "/admin", label: "Overview" },
    { href: "/tickets", label: "Manage tickets" },
    { href: "/kb", label: "Knowledge base" },
    { href: "/rag-eval", label: "Retrieval evaluation" },
    { href: "/review", label: "Knowledge review" },
    { href: "/observability", label: "Observability & costs" },
    { href: "/topics", label: "Topics" },
    { href: "/acceptance", label: "Classifier validation", children: [
      ["/acceptance", "Overview"], ["/acceptance/eval", "Evaluation"],
      ["/acceptance/data", "Data"], ["/acceptance/errors", "Errors"],
    ] },
  ];
  const CAT = '<img src="/static/paws.svg" alt="" aria-hidden="true">';
  function node(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }
  function link(href, label, on) {
    const a = node("a", on ? "on" : "", label);
    a.href = href;
    if (on) a.setAttribute("aria-current", "page");
    return a;
  }
  function moduleOf(active) {
    return NAV.find(m => m.href === active) || NAV.find(m => active.startsWith(m.href + "/"));
  }
  function renderAdminNav(active) {
    if (!document.getElementById("mh-admin-css")) {
      const css = node("link"); css.id = "mh-admin-css"; css.rel = "stylesheet"; css.href = "/static/admin.css";
      document.head.appendChild(css);
    }
    const aside = node("aside", "mh-sidebar"); aside.id = "mh-sidebar"; aside.setAttribute("aria-label", "Admin navigation");
    const brand = node("div", "mh-brand"), mascot = node("div", "mh-mascot"), title = node("div");
    mascot.innerHTML = CAT;
    title.append(node("strong", null, "Paw & Hearth"), node("small", null, "Admin"));
    const close = node("button", null, "✕"); close.id = "mh-close"; close.type = "button"; close.setAttribute("aria-label", "Close admin navigation");
    brand.append(mascot, title, close);
    const nav = node("nav", "mh-navlinks"); nav.setAttribute("aria-label", "Admin modules");
    const mod = moduleOf(active);
    for (const m of NAV) {
      nav.append(link(m.href, m.label, m === mod));
    }
    const account = node("div", "mh-account"), identity = node("div", "mh-identity"), avatar = node("span", "mh-avatar", "A"), copy = node("div", "mh-identity-copy"), name = node("strong", null, "Administrator");
    avatar.setAttribute("aria-hidden", "true"); copy.append(node("small", null, "Signed in as"), name); identity.append(avatar, copy);
    const logout = node("button", null, "Sign out"); logout.type = "button";
    account.append(identity, logout);
    aside.append(brand, nav, account);
    fetch("/api/auth/me").then(async response => {
      if (response.status === 401) { location.href = "/login"; return; }
      if (!response.ok) throw new Error("Could not load account details");
      const user = await response.json();
      if (user.role !== "admin") { location.href = user.role === "support" ? "/support" : "/"; return; }
      name.textContent = user.username; avatar.textContent = Array.from(user.username)[0].toUpperCase();
    }).catch(() => { name.textContent = "Account temporarily unavailable"; });
    logout.onclick = async () => {
      logout.disabled = true;
      try {
        const response = await fetch("/api/auth/logout", { method: "POST" });
        if (!response.ok) throw new Error("Could not sign out. Please try again");
        localStorage.removeItem("commerceagent_conversation_id"); location.href = "/login";
      } catch (error) { logout.disabled = false; alert(error.message); }
    };
    return aside;
  }
  function mountAdminNav(active) {
    if (document.querySelector(".mh-shell")) return document.getElementById("mh-sidebar");
    document.body.classList.add("mh-admin");
    const wrap = document.querySelector(".wrap"), bar = wrap.querySelector(".topbar");
    const shell = node("div", "mh-shell"), workspace = node("main", "mh-workspace"), aside = renderAdminNav(active);
    wrap.parentNode.insertBefore(shell, wrap); workspace.append(wrap); shell.append(aside, workspace);
    if (bar) {
      bar.querySelectorAll(":scope > .sub").forEach(el => el.remove());
      const menu = node("button", null, "☰ Navigation"); menu.type = "button"; menu.id = "mh-menu";
      menu.setAttribute("aria-controls", "mh-sidebar"); menu.setAttribute("aria-expanded", "false"); bar.prepend(menu);
      const backdrop = node("button", "mh-backdrop"); backdrop.type = "button"; backdrop.hidden = true; backdrop.tabIndex = -1; backdrop.setAttribute("aria-label", "Close admin navigation"); document.body.append(backdrop);
      const narrow = matchMedia("(max-width: 900px)");
      function closeMenu(focus = true) {
        const wasOpen = aside.classList.contains("open"); aside.classList.remove("open"); aside.removeAttribute("role"); aside.removeAttribute("aria-modal"); backdrop.hidden = true; workspace.inert = false; menu.setAttribute("aria-expanded", "false");
        if (wasOpen && focus && narrow.matches) menu.focus();
      }
      menu.onclick = () => {
        aside.classList.add("open"); aside.setAttribute("role", "dialog"); aside.setAttribute("aria-modal", "true"); backdrop.hidden = false; workspace.inert = true; menu.setAttribute("aria-expanded", "true"); document.getElementById("mh-close").focus();
      };
      document.getElementById("mh-close").onclick = () => closeMenu(); backdrop.onclick = () => closeMenu(); narrow.addEventListener("change", () => closeMenu(false));
      document.addEventListener("keydown", event => {
        if (!aside.classList.contains("open")) return;
        if (event.key === "Escape") { event.preventDefault(); closeMenu(); }
        if (event.key === "Tab") {
          const controls = [...aside.querySelectorAll("button:not(:disabled),a[href]")].filter(el => el.getClientRects().length), first = controls[0], last = controls[controls.length - 1];
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
      });
    }
    const mod = moduleOf(active);
    if (mod && mod.children) {
      const sub = node("nav", "mh-subnav"); sub.setAttribute("aria-label", "Classifier validation");
      for (const [href, label] of mod.children) sub.append(link(href, label, href === active));
      if (bar) bar.after(sub); else wrap.prepend(sub);
    }
    wrap.querySelectorAll(":scope > .tip, :scope > .gates").forEach(tip => {
      const details = node("details", "mh-help"), summary = node("summary", null, "Help");
      tip.before(details); details.append(summary, tip);
    });
    return aside;
  }
  window.renderAdminNav = renderAdminNav;
  window.mountAdminNav = mountAdminNav;
})();
