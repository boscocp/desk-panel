// Measure the panel against the viewport. Runs inside the page, returns JSON
// to check_layout.py, and changes nothing it measures.
//
// Three questions, because "it rendered" answers none of them:
//   1. is the document taller than the screen (the page scrolls, something is
//      below the fold),
//   2. is any single element outside the viewport box (one card escaped),
//   3. does any section clip its own content (the card is on screen but what is
//      in it is not).
// T2.3 shipped a panel that passed a screenshot and failed all three.

const SECTIONS = ['clock', 'date', 'quotes', 'fx', 'crypto', 'weather', 'battery'];

const out = {
    viewport: [window.innerWidth, window.innerHeight],
    doc: [document.documentElement.scrollWidth, document.documentElement.scrollHeight],
    sections: {},
    outsideViewport: [],
    clippedContent: [],
    emptySections: [],
};

function outside(r) {
    return r.top < -0.5 || r.left < -0.5 ||
           r.bottom > window.innerHeight + 0.5 || r.right > window.innerWidth + 0.5;
}

for (const id of SECTIONS) {
    const el = document.getElementById(id);
    if (!el) {
        out.sections[id] = null;
        out.outsideViewport.push('#' + id + ' is missing from the DOM');
        continue;
    }
    const r = el.getBoundingClientRect();
    const text = (el.textContent || '').trim();
    out.sections[id] = {
        left: Math.round(r.left), top: Math.round(r.top),
        right: Math.round(r.right), bottom: Math.round(r.bottom),
        width: Math.round(r.width), height: Math.round(r.height),
        text: text.slice(0, 80),
    };
    if (!text) {
        out.emptySections.push(id);
    }
    // scrollHeight > clientHeight means the box is on screen but its content
    // does not fit inside it. Cards use overflow:hidden, so this is silent.
    if (el.scrollHeight > el.clientHeight + 0.5 || el.scrollWidth > el.clientWidth + 0.5) {
        out.clippedContent.push(
            '#' + id + ' content ' + el.scrollWidth + 'x' + el.scrollHeight +
            ' in a box of ' + el.clientWidth + 'x' + el.clientHeight);
    }
}

// Not just the five sections: any descendant can escape, and a row sticking out
// of a card is as broken as a card sticking out of the page.
document.querySelectorAll('body *').forEach((el) => {
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) {
        return;
    }
    if (outside(r)) {
        const name = el.id ? '#' + el.id
            : el.tagName.toLowerCase() + (el.className ? '.' + el.className : '');
        out.outsideViewport.push(
            name + ' at [' + Math.round(r.left) + ',' + Math.round(r.top) + ' to ' +
            Math.round(r.right) + ',' + Math.round(r.bottom) + ']');
    }
});

// The clock is also T2.2's marker: MainActivity reads #clock out of the DOM on
// load and logs panel=rendered clock="HH:MM:SS". If the id or the format goes,
// that acceptance breaks somewhere far away from here.
const clock = document.getElementById('clock');
out.clockText = clock ? clock.textContent : null;
if (!clock || !/^\d{2}:\d{2}:\d{2}$/.test((clock.textContent || '').trim())) {
    out.outsideViewport.push('#clock is not HH:MM:SS, which breaks T2.2 panel=rendered');
}

return out;
