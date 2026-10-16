"""Record form fills for Landed Applications → Questions & answers.

Produces ``fill`` step ``outcomes`` matching the Node browser-worker shape so
the Landed UI can show them with source ``apply-agents``.
"""

from __future__ import annotations

from typing import Any

FILL_SOURCE = "apply-agents"
PASSWORD_REDACTED = "[redacted]"
MAX_OUTCOMES_PER_STEP = 80

# Playwright page.evaluate script: scrape value-bearing controls on the page.
SCRAPE_FILLED_JS = """() => {
  const skipTypes = new Set([
    'hidden', 'submit', 'button', 'image', 'reset', 'file'
  ]);
  const clean = (s) => String(s || '').replace(/\\s+/g, ' ').trim();

  function labelFor(el) {
    if (!el) return '';
    const aria = clean(el.getAttribute('aria-label'));
    if (aria) return aria;
    if (el.id) {
      const byFor = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (byFor) {
        const t = clean(byFor.innerText || byFor.textContent);
        if (t) return t;
      }
    }
    const wrap = el.closest('label');
    if (wrap) {
      const t = clean(wrap.innerText || wrap.textContent);
      if (t) return t.slice(0, 160);
    }
    const labelled = el.getAttribute('aria-labelledby');
    if (labelled) {
      const parts = labelled.split(/\\s+/).map((id) => {
        const n = document.getElementById(id);
        return n ? clean(n.innerText || n.textContent) : '';
      }).filter(Boolean);
      if (parts.length) return parts.join(' ').slice(0, 160);
    }
    const ph = clean(el.getAttribute('placeholder'));
    if (ph) return ph;
    const name = clean(el.getAttribute('name'));
    if (name) return name;
    const id = clean(el.id);
    if (id) return id;
    return el.tagName ? el.tagName.toLowerCase() : 'field';
  }

  function selectorFor(el) {
    if (!el) return null;
    if (el.id) return '#' + CSS.escape(el.id);
    const name = el.getAttribute('name');
    if (name) {
      const tag = (el.tagName || '').toLowerCase();
      return `${tag}[name="${name.replace(/"/g, '\\\\"')}"]`;
    }
    return null;
  }

  function fieldType(el) {
    const tag = (el.tagName || '').toLowerCase();
    if (tag === 'select') return 'select';
    if (tag === 'textarea') return 'textarea';
    if (el.isContentEditable) return 'contenteditable';
    return clean(el.getAttribute('type') || 'text').toLowerCase() || 'text';
  }

  function valueOf(el) {
    const tag = (el.tagName || '').toLowerCase();
    const type = fieldType(el);
    if (type === 'password') return { text: '[redacted]', password: true };
    if (type === 'checkbox' || type === 'radio') {
      if (!el.checked) return null;
      const v = clean(el.value);
      return { text: v && v !== 'on' ? v : 'Yes', password: false };
    }
    if (tag === 'select') {
      const opt = el.selectedOptions && el.selectedOptions[0];
      const text = clean((opt && (opt.label || opt.textContent)) || el.value);
      return text ? { text, password: false } : null;
    }
    if (el.isContentEditable) {
      const text = clean(el.innerText || el.textContent);
      return text ? { text: text.slice(0, 2000), password: false } : null;
    }
    const text = clean(el.value);
    return text ? { text: text.slice(0, 2000), password: false } : null;
  }

  const nodes = Array.from(document.querySelectorAll(
    'input, textarea, select, [contenteditable="true"]'
  ));
  const out = [];
  const seen = new Set();
  for (const el of nodes) {
    const type = fieldType(el);
    if (skipTypes.has(type)) continue;
    if (el.disabled || el.readOnly) {
      // still record if it has a value (some ATS lock after fill)
    }
    const style = window.getComputedStyle(el);
    if (style && (style.display === 'none' || style.visibility === 'hidden')) continue;
    const val = valueOf(el);
    if (!val || !val.text) continue;
    const label = labelFor(el) || type;
    const key = (label + '|' + val.text).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      label,
      text: val.text,
      fieldType: type,
      selector: selectorFor(el),
      name: clean(el.getAttribute('name')) || null,
    });
  }
  return out;
}"""

FOCUS_META_JS = """() => {
  const el = document.activeElement;
  if (!el) return null;
  const tag = (el.tagName || '').toLowerCase();
  const editable = !!el.isContentEditable;
  if (!['input', 'textarea', 'select'].includes(tag) && !editable) return null;
  const clean = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
  let fieldType = 'text';
  if (tag === 'select') fieldType = 'select';
  else if (tag === 'textarea') fieldType = 'textarea';
  else if (editable) fieldType = 'contenteditable';
  else fieldType = clean(el.getAttribute('type') || 'text').toLowerCase() || 'text';
  let label = clean(el.getAttribute('aria-label'));
  if (!label && el.id) {
    const byFor = document.querySelector('label[for=\"' + CSS.escape(el.id) + '\"]');
    if (byFor) label = clean(byFor.innerText || byFor.textContent);
  }
  if (!label) {
    const wrap = el.closest('label');
    if (wrap) label = clean(wrap.innerText || wrap.textContent).slice(0, 160);
  }
  if (!label) label = clean(el.getAttribute('placeholder') || el.getAttribute('name') || el.id || tag);
  return {
    label: label || fieldType,
    fieldType,
    name: clean(el.getAttribute('name')) || null,
    selector: el.id ? ('#' + CSS.escape(el.id)) : null,
  };
}"""


def outcome_key(item: dict[str, Any]) -> str:
    label = str(item.get("label") or "").strip().lower()
    name = str(item.get("name") or "").strip().lower()
    return name or label or str(item.get("selector") or "").strip().lower()


def to_outcome(
    *,
    label: str,
    text: str,
    field_type: str | None = None,
    selector: str | None = None,
    name: str | None = None,
    source: str = FILL_SOURCE,
    ok: bool = True,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "label": str(label or "field").strip() or "field",
        "text": str(text).strip(),
        "source": source,
        "ok": bool(ok),
    }
    if field_type:
        out["fieldType"] = str(field_type)
    if selector:
        out["selector"] = str(selector)
    if name:
        out["name"] = str(name)
        out["key"] = str(name)
    return out


def merge_fill_outcomes(
    scraped: list[dict[str, Any]] | None,
    typed: list[dict[str, Any]] | None,
    *,
    source: str = FILL_SOURCE,
) -> list[dict[str, Any]]:
    """Merge typed log with DOM scrape; scrape wins on the same control key."""
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def _put(raw: dict[str, Any], *, prefer: bool) -> None:
        label = str(raw.get("label") or "").strip()
        text = str(raw.get("text") or "").strip()
        if not label or not text:
            return
        field_type = str(raw.get("fieldType") or raw.get("field_type") or "").strip() or None
        if field_type == "password" or text == PASSWORD_REDACTED:
            text = PASSWORD_REDACTED
            field_type = field_type or "password"
        item = to_outcome(
            label=label,
            text=text,
            field_type=field_type,
            selector=str(raw.get("selector") or "").strip() or None,
            name=str(raw.get("name") or "").strip() or None,
            source=source,
            ok=raw.get("ok", True) is not False,
        )
        key = outcome_key(item) or item["label"].lower()
        if key in by_key and not prefer:
            return
        if key not in by_key:
            order.append(key)
        by_key[key] = item

    for row in typed or []:
        if isinstance(row, dict):
            _put(row, prefer=False)
    for row in scraped or []:
        if isinstance(row, dict):
            _put(row, prefer=True)

    return [by_key[k] for k in order if k in by_key]


def chunk_outcomes(
    outcomes: list[dict[str, Any]],
    *,
    size: int = MAX_OUTCOMES_PER_STEP,
) -> list[list[dict[str, Any]]]:
    if not outcomes:
        return []
    n = max(1, int(size))
    return [outcomes[i : i + n] for i in range(0, len(outcomes), n)]


def fill_step_detail(
    outcomes: list[dict[str, Any]],
    *,
    page: int = 1,
    applier: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "page": page,
        "filled": [str(o.get("label") or "") for o in outcomes if o.get("label")],
        "outcomes": outcomes,
    }
    if applier:
        detail["applier"] = applier
    return detail
