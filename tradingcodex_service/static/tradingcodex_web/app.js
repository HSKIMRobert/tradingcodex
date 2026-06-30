(() => {
  const scrollKey = "tcxWebScrollY";
  const pathKey = "tcxWebScrollPath";
  const shellSelector = ".tc-main-shell";
  const statefulLinks = "a.tc-agent-chip, a.tc-segmented-control a, a.tc-skill-link";

  const shell = () => document.querySelector(shellSelector);
  const all = (root, selector) => Array.from(root.querySelectorAll(selector));

  const initShell = () => {
    const app = document.querySelector("[data-tcx-shell]");
    if (!app || app.dataset.tcxReady) return;
    app.dataset.tcxReady = "1";
    const sidebar = app.querySelector(".tc-sidebar");
    const toggle = app.querySelector("[data-tcx-nav-toggle]");
    const setOpen = (open) => {
      sidebar?.classList.toggle("is-open", open);
      toggle?.setAttribute("aria-expanded", String(open));
    };
    const setWidth = (width) => {
      const clamped = Math.min(520, Math.max(260, width));
      app.style.setProperty("--tc-sidebar-width", `${clamped}px`);
      localStorage.setItem("tcxSidebarWidth", String(clamped));
    };
    setWidth(Number(localStorage.getItem("tcxSidebarWidth") || 320));
    toggle?.addEventListener("click", () => setOpen(!sidebar?.classList.contains("is-open")));
    all(app, "[data-tcx-nav-close]").forEach((link) => link.addEventListener("click", () => setOpen(false)));
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape") setOpen(false);
    });
    app.querySelector("[data-tcx-sidebar-resizer]")?.addEventListener("mousedown", (event) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = Number.parseInt(getComputedStyle(app).getPropertyValue("--tc-sidebar-width"), 10) || 320;
      const onMove = (moveEvent) => setWidth(startWidth + moveEvent.clientX - startX);
      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        document.body.classList.remove("tc-resizing-sidebar");
      };
      document.body.classList.add("tc-resizing-sidebar");
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    });
  };

  const initMcpPage = () => {
    const page = document.querySelector("[data-tcx-mcp-page]");
    if (!page || page.dataset.tcxReady) return;
    page.dataset.tcxReady = "1";
    let selectedRouter = page.dataset.selectedRouter || "";
    let selectedTool = page.dataset.selectedTool || "";
    const modal = page.querySelector("[data-tcx-modal-backdrop]");
    const render = () => {
      all(page, "[data-router-name].tc-mcp-router-card").forEach((card) => {
        card.classList.toggle("is-active", card.dataset.routerName === selectedRouter);
      });
      all(page, "[data-tcx-tool-card]").forEach((card) => {
        const visible = !selectedRouter || card.dataset.routerName === selectedRouter;
        card.hidden = !visible;
        card.classList.toggle("is-active", card.dataset.toolId === selectedTool);
      });
      all(page, "[data-tcx-tool-controls]").forEach((panel) => {
        panel.hidden = panel.dataset.toolId !== selectedTool;
      });
      const empty = page.querySelector("[data-tcx-no-tool]");
      if (empty) empty.hidden = Boolean(selectedTool);
    };
    all(page, "[data-tcx-select-router]").forEach((button) => {
      button.addEventListener("click", () => {
        selectedRouter = button.dataset.routerName || "";
        selectedTool = "";
        render();
      });
    });
    all(page, "[data-tcx-tool-card]").forEach((button) => {
      button.addEventListener("click", () => {
        selectedTool = button.dataset.toolId || "";
        selectedRouter = button.dataset.routerName || selectedRouter;
        render();
      });
    });
    page.querySelector("[data-tcx-modal-open]")?.addEventListener("click", () => {
      if (modal) modal.hidden = false;
    });
    all(page, "[data-tcx-modal-close]").forEach((button) => button.addEventListener("click", () => {
      if (modal) modal.hidden = true;
    }));
    modal?.addEventListener("click", (event) => {
      if (event.target === modal) modal.hidden = true;
    });
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && modal) modal.hidden = true;
    });
    render();
  };

  const initTopology = () => {
    const root = document.querySelector("[data-tcx-topology]");
    if (!root || root.dataset.tcxReady) return;
    root.dataset.tcxReady = "1";
    const renderEdges = () => {
      all(root, "[data-tcx-edge-toggle]").forEach((toggle) => {
        all(root, `[data-edge-group="${toggle.dataset.edgeGroup}"]`).forEach((item) => {
          if (item !== toggle) item.hidden = !toggle.checked;
        });
      });
    };
    all(root, "[data-tcx-edge-toggle]").forEach((toggle) => toggle.addEventListener("change", renderEdges));
    all(root, "[data-tcx-select-role]").forEach((button) => {
      button.addEventListener("click", () => {
        all(root, "[data-tcx-select-role]").forEach((node) => node.classList.toggle("is-selected", node === button));
      });
    });
    renderEdges();
  };

  const saveScroll = () => {
    const target = shell();
    if (!target) return;
    sessionStorage.setItem(scrollKey, String(target.scrollTop));
    sessionStorage.setItem(pathKey, window.location.pathname);
  };

  const applyAfterLayout = (callback) => {
    callback();
    requestAnimationFrame(callback);
    setTimeout(callback, 40);
    setTimeout(callback, 140);
  };

  const clearSavedScroll = () => {
    sessionStorage.removeItem(scrollKey);
    sessionStorage.removeItem(pathKey);
  };

  const scrollToHashTarget = () => {
    if (!window.location.hash) return false;
    const target = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
    const scrollShell = shell();
    if (!target || !scrollShell) return false;

    applyAfterLayout(() => {
      const shellRect = scrollShell.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      scrollShell.scrollTop += targetRect.top - shellRect.top - 10;
    });
    clearSavedScroll();
    return true;
  };

  const restoreScroll = () => {
    const saved = sessionStorage.getItem(scrollKey);
    const savedPath = sessionStorage.getItem(pathKey);
    if (!saved) return;
    if (savedPath && savedPath !== window.location.pathname) {
      clearSavedScroll();
      return;
    }

    const y = Number(saved);
    if (!Number.isFinite(y)) {
      clearSavedScroll();
      return;
    }

    applyAfterLayout(() => {
      const target = shell();
      if (target) target.scrollTop = y;
    });
    setTimeout(clearSavedScroll, 140);
  };

  window.addEventListener("DOMContentLoaded", () => {
    initShell();
    initMcpPage();
    initTopology();
    if (!scrollToHashTarget()) restoreScroll();
  });
  window.addEventListener("pagehide", saveScroll);
  window.addEventListener("beforeunload", saveScroll);
  document.addEventListener("htmx:beforeRequest", saveScroll);
  document.addEventListener("htmx:afterSettle", () => {
    if (!window.location.hash) restoreScroll();
  });
  document.addEventListener("click", (event) => {
    const link = event.target instanceof Element ? event.target.closest(statefulLinks) : null;
    if (link) saveScroll();
  });
})();
