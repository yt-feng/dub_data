"""Extract listing cards from a rendered dubizzle results page.

dubizzle renders each listing as a `data-testid="listing-<n>"` card whose
sub-fields carry `data-testid="listing-<field>"` (price, year, kms, location,
bedrooms, …). We read those directly — reliable across verticals — and fall
back to a price-anchored heuristic if the testids ever change. Image URLs are
captured as-is (we keep only the original `dbz-images` URLs).
"""

from __future__ import annotations

import re

# JS evaluated in the page. Returns a list of raw card dicts.
EXTRACT_JS = r"""
() => {
  const cardEls = [...document.querySelectorAll('[data-testid]')]
    .filter(e => /^listing-\d+$/.test(e.getAttribute('data-testid')));

  const readCard = (c) => {
    // The detail <a> may wrap the card (ancestor) or sit inside it.
    const root = c.closest('a[href]') || c;
    const a = (root.tagName === 'A') ? root : (root.querySelector('a[href]') || c.querySelector('a[href]'));
    const fields = {};
    c.querySelectorAll('[data-testid]').forEach(e => {
      const m = (e.getAttribute('data-testid') || '').match(/^listing-(.+)$/);
      if (m && !/^\d+$/.test(m[1])) {
        const v = (e.innerText || '').replace(/\s+/g, ' ').trim();
        if (v && !(m[1] in fields)) fields[m[1]] = v;
      }
    });
    const headings = [...c.querySelectorAll('[data-testid^="heading-text"],[data-testid="subheading-text"]')]
      .map(e => (e.innerText || '').trim()).filter(Boolean);
    const imgs = [...root.querySelectorAll('img')]
      .map(i => i.currentSrc || i.src || i.getAttribute('data-src') || '')
      .filter(s => s.includes('dbz-images'));
    return {
      url: a ? a.href : '',
      title: (a && (a.getAttribute('aria-label') || a.title)) || headings.join(' ') || (fields['title'] || ''),
      price_text: fields['price'] || '',
      year_text: fields['year'] || '',
      kms_text: fields['kms'] || fields['kilometers'] || '',
      location: fields['location'] || '',
      bedrooms_text: fields['bedrooms'] || fields['beds'] || '',
      bathrooms_text: fields['bathrooms'] || fields['baths'] || '',
      area_text: fields['area'] || fields['size'] || '',
      images: [...new Set(imgs)],
      fields,
      text: (c.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 700),
    };
  };

  if (cardEls.length) return cardEls.map(readCard);

  // --- fallback: price-anchored heuristic ---
  const PRICE = /(AED|درهم|EGP)/i;
  const isDetail = h => !!h && /\/[a-f0-9]{16,}\/?$|ID\d|\/ad\//i.test(h);
  const seen = new Set(), cards = [];
  for (const leaf of [...document.querySelectorAll('div,span,p,strong')].filter(e => PRICE.test(e.textContent || '') && /\d/.test(e.textContent || ''))) {
    let c = leaf, link = null;
    for (let i = 0; i < 9 && c; i++) {
      c = c.parentElement; if (!c) break;
      const a = [...c.querySelectorAll('a[href]')].find(a => isDetail(a.getAttribute('href')));
      if (a && c.querySelector('img')) { link = a; break; }
    }
    if (!c || !link || seen.has(c)) continue;
    seen.add(c);
    cards.push({
      url: link.href,
      title: (link.getAttribute('aria-label') || '').trim(),
      price_text: (leaf.textContent || '').trim(),
      images: [...new Set([...c.querySelectorAll('img')].map(i => i.currentSrc || i.src).filter(s => s && s.includes('dbz-images')))],
      text: (c.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 700),
      fields: {},
    });
  }
  return cards;
}
"""

_NUM = re.compile(r"[\d][\d,]*")
_BEDS = re.compile(r"(\d+)\s*(?:bed|bd|bhk|br\b)", re.I)
_BATHS = re.compile(r"(\d+)\s*(?:bath|ba\b)", re.I)
_AREA = re.compile(r"([\d,]+)\s*(?:sq\.?\s*ft|sqft|sq\.?\s*m|sqm)", re.I)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_KM = re.compile(r"([\d,]+)\s*km\b", re.I)


def _int(s) -> int | str:
    if s in (None, "", []):
        return ""
    m = _NUM.search(str(s).replace(",", ""))
    return int(m.group()) if m else ""


def normalize(card: dict) -> dict:
    """Add parsed numeric fields, preferring explicit testid values, then
    falling back to parsing the card's text."""
    text = card.get("text", "")
    card["price"] = _int(card.get("price_text"))
    card["year"] = (_int(card.get("year_text")) or
                    (int(_YEAR.search(text).group()) if _YEAR.search(text) else ""))
    card["kilometers"] = (_int(card.get("kms_text")) or
                          (_int(_KM.search(text).group(1)) if _KM.search(text) else ""))
    card["bedrooms"] = (_int(card.get("bedrooms_text")) or
                        (int(_BEDS.search(text).group(1)) if _BEDS.search(text) else ""))
    card["bathrooms"] = (_int(card.get("bathrooms_text")) or
                         (int(_BATHS.search(text).group(1)) if _BATHS.search(text) else ""))
    card["size"] = (_int(card.get("area_text")) or
                    (_int(_AREA.search(text).group(1)) if _AREA.search(text) else ""))
    return card
