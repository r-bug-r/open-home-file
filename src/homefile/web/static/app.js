/* Progressive enhancement only. Every action below also works without this
   file: field rows are real links, forms post normally, and the citation for
   the selected field is rendered on the server. */

(function () {
  "use strict";

  function highlightIn(pageEl, start, end) {
    pageEl.querySelectorAll("mark.citation-mark").forEach(function (mark) {
      var parent = mark.parentNode;
      while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
      parent.removeChild(mark);
      parent.normalize();
    });
    var node = pageEl.firstChild;
    if (!node || node.nodeType !== Node.TEXT_NODE) return null;
    var text = node.nodeValue || "";
    var from = Math.max(0, Math.min(start, text.length));
    var to = Math.max(from, Math.min(end, text.length));
    if (to <= from) return null;
    var range = document.createRange();
    range.setStart(node, from);
    range.setEnd(node, to);
    var mark = document.createElement("mark");
    mark.className = "citation-mark";
    mark.id = "citation-target";
    mark.appendChild(range.extractContents());
    range.insertNode(mark);
    return mark;
  }

  function selectField(row, options) {
    var settings = options || {};
    var workspace = document.querySelector("[data-workspace]");
    if (!workspace) return;

    workspace.querySelectorAll(".field-row").forEach(function (item) {
      item.setAttribute("aria-current", item === row ? "true" : "false");
    });

    var fieldId = row.getAttribute("data-field-id") || "";
    var pageNo = row.getAttribute("data-page");
    var start = parseInt(row.getAttribute("data-start") || "0", 10);
    var end = parseInt(row.getAttribute("data-end") || "0", 10);
    var name = row.getAttribute("data-name") || "";
    var value = row.getAttribute("data-value") || "";
    var confidence = row.getAttribute("data-confidence") || "";

    workspace.querySelectorAll("[data-page-tab]").forEach(function (tab) {
      tab.setAttribute("aria-selected", tab.getAttribute("data-page-tab") === pageNo ? "true" : "false");
    });
    workspace.querySelectorAll("[data-page-panel]").forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-page-panel") !== pageNo;
    });

    var pageEl = workspace.querySelector('[data-page-panel="' + pageNo + '"] .source-text');
    if (pageEl) {
      var mark = highlightIn(pageEl, start, end);
      if (mark && settings.scroll !== false && mark.scrollIntoView) {
        mark.scrollIntoView({ block: "center", inline: "nearest" });
      }
    }

    var quoteEl = workspace.querySelector("[data-citation-quote]");
    if (quoteEl) quoteEl.textContent = row.getAttribute("data-quote") || "";

    var titleEl = workspace.querySelector("[data-citation-field]");
    if (titleEl) titleEl.textContent = name.replace(/_/g, " ");

    var valueEl = workspace.querySelector("[data-citation-value]");
    if (valueEl) valueEl.textContent = value;

    var confEl = workspace.querySelector("[data-citation-confidence]");
    if (confEl) confEl.textContent = confidence ? Math.round(Number(confidence) * 100) + "%" : "—";

    // The correction form is shared by every field, so retarget it to the row
    // the user just chose. Without this the form would post the field that was
    // selected when the page rendered.
    var form = workspace.querySelector("[data-citation-form]");
    if (form) {
      var hidden = form.querySelector('input[name="field_id"]');
      if (hidden) hidden.value = fieldId;
      var input = form.querySelector('input[name="value"]');
      if (input) input.value = value;
      var reason = form.querySelector('input[name="reason"]');
      if (reason && settings.resetReason !== false) reason.value = "";
    }

    workspace.querySelectorAll("[data-reminder-for]").forEach(function (block) {
      block.hidden = block.getAttribute("data-reminder-for") !== fieldId;
    });

    var live = document.getElementById("citation-live");
    if (live) {
      live.textContent =
        name.replace(/_/g, " ") +
        " on page " +
        pageNo +
        ". Citation: " +
        (row.getAttribute("data-quote") || "").slice(0, 120);
    }

    if (window.history && window.history.replaceState) {
      var url = new URL(window.location.href);
      url.searchParams.set("field", fieldId);
      window.history.replaceState({}, "", url);
    }
  }

  function initWorkspace() {
    var workspace = document.querySelector("[data-workspace]");
    if (!workspace) return;

    workspace.querySelectorAll(".field-row").forEach(function (row) {
      row.addEventListener("click", function (event) {
        if (event.metaKey || event.ctrlKey || event.shiftKey) return;
        event.preventDefault();
        selectField(row);
        var citation = workspace.querySelector("[data-citation-pane]");
        if (citation && citation.focus) {
          citation.focus({ preventScroll: true });
        }
      });
    });

    workspace.querySelectorAll("[data-page-tab]").forEach(function (tab) {
      tab.addEventListener("click", function () {
        var pageNo = tab.getAttribute("data-page-tab");
        workspace.querySelectorAll("[data-page-tab]").forEach(function (item) {
          item.setAttribute("aria-selected", item === tab ? "true" : "false");
        });
        workspace.querySelectorAll("[data-page-panel]").forEach(function (panel) {
          panel.hidden = panel.getAttribute("data-page-panel") !== pageNo;
        });
      });
    });

    var current = workspace.querySelector('.field-row[aria-current="true"]');
    if (current) selectField(current, { scroll: false, resetReason: false });
  }

  function initDropzone() {
    document.querySelectorAll("[data-dropzone]").forEach(function (zone) {
      var input = zone.querySelector('input[type="file"]');
      if (!input) return;
      ["dragenter", "dragover"].forEach(function (name) {
        zone.addEventListener(name, function (event) {
          event.preventDefault();
          zone.classList.add("is-dragging");
        });
      });
      ["dragleave", "dragend", "drop"].forEach(function (name) {
        zone.addEventListener(name, function (event) {
          event.preventDefault();
          zone.classList.remove("is-dragging");
        });
      });
      zone.addEventListener("drop", function (event) {
        if (!event.dataTransfer || !event.dataTransfer.files.length) return;
        input.files = event.dataTransfer.files;
        var status = zone.querySelector("[data-dropzone-status]");
        if (status) {
          status.textContent =
            event.dataTransfer.files.length + " file(s) ready. Choose Import to process them.";
        }
        var submit = zone.querySelector('button[type="submit"]');
        if (submit) submit.focus();
      });
      input.addEventListener("change", function () {
        var status = zone.querySelector("[data-dropzone-status]");
        if (status && input.files) {
          status.textContent =
            input.files.length === 0
              ? ""
              : input.files.length + " file(s) ready. Choose Import to process them.";
        }
      });
    });
  }

  function initSearchShortcut() {
    document.addEventListener("keydown", function (event) {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      var target = event.target;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        return;
      }
      var search = document.querySelector('input[type="search"]');
      if (search) {
        event.preventDefault();
        search.focus();
      }
    });
  }

  function initConfirm() {
    document.querySelectorAll("[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        var message = form.getAttribute("data-confirm") || "Continue?";
        if (!window.confirm(message)) event.preventDefault();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initWorkspace();
    initDropzone();
    initSearchShortcut();
    initConfirm();
  });
})();
