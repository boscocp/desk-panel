// Measure the panel against the viewport. Runs inside the page, returns JSON
// to check_layout.py, and changes nothing it measures.
//
// Four questions, because "it rendered" answers none of them:
//   1. is the document taller than the screen (the page scrolls, something is
//      below the fold),
//   2. is any single element outside the viewport box (one card escaped),
//   3. does any section clip its own content (the card is on screen but what is
//      in it is not),
//   4. does one section's text sit on top of another's (everything fits, and
//      some of it is underneath the rest).
// T2.3 shipped a panel that passed a screenshot and failed the first three.
// Question 4 arrived later, in T5.4, and it arrived the hard way: the battery
// corner line is positioned absolutely and set to nowrap, so its longest
// variant grew out of its own column and painted an opaque black box over the
// bottom of the CRYPTO card -- hiding a live price's change and sparkline. The
// harness passed. Nothing here was looking, and a comment in style.css claimed
// otherwise.

const SECTIONS = ['clock', 'date', 'quotes', 'fx', 'crypto', 'weather', 'battery',
                  'stale-badge'];

const out = {
    viewport: [window.innerWidth, window.innerHeight],
    doc: [document.documentElement.scrollWidth, document.documentElement.scrollHeight],
    sections: {},
    outsideViewport: [],
    clippedContent: [],
    emptySections: [],
    overlaps: [],
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

// Question 4: does one section's ink land on another's?
//
// Boxes are the wrong thing to compare. Two sections are allowed to share a
// rectangle -- #battery deliberately sits in the foot of the WEATHER card, and
// #stale-badge deliberately sits over the corner of #panel -- and a check on
// boxes would either fail on both of those or have to allowlist the exact pair
// the T5.4 bug was in. So this compares what is actually drawn: the leaf
// elements that carry text, and the <path> of each sparkline. Sharing empty
// space is fine. Sharing a pixel that has a glyph or a line in it is not.
function ink(root) {
    const found = [];
    root.querySelectorAll('*').forEach((el) => {
        // Leaves only: a container's rect covers its children, which would
        // report every nesting as an overlap with itself.
        if (el.children.length) {
            return;
        }
        const tag = el.tagName.toLowerCase();
        const drawsSomething = (el.textContent || '').trim() !== '' || tag === 'path';
        if (!drawsSomething) {
            return;
        }
        const r = el.getBoundingClientRect();
        if (r.width < 0.5 || r.height < 0.5) {
            return;
        }
        found.push({ r: r, what: ((el.textContent || '').trim() || tag).slice(0, 24) });
    });
    return found;
}

// Half a pixel of tolerance, the same as every other comparison here: adjacent
// boxes routinely share an edge at fractional device pixel ratios, and an edge
// is not an overlap.
function collides(a, b) {
    return a.left < b.right - 0.5 && b.left < a.right - 0.5 &&
           a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;
}

const inkBySection = {};
for (const id of SECTIONS) {
    const el = document.getElementById(id);
    // A hidden section (#stale-badge most of the time) has no ink to collide.
    inkBySection[id] = el && el.offsetParent !== null ? ink(el) : [];
}

for (let i = 0; i < SECTIONS.length; i += 1) {
    for (let j = i + 1; j < SECTIONS.length; j += 1) {
        for (const a of inkBySection[SECTIONS[i]]) {
            for (const b of inkBySection[SECTIONS[j]]) {
                if (!collides(a.r, b.r)) {
                    continue;
                }
                const w = Math.round(Math.min(a.r.right, b.r.right) -
                                     Math.max(a.r.left, b.r.left));
                const h = Math.round(Math.min(a.r.bottom, b.r.bottom) -
                                     Math.max(a.r.top, b.r.top));
                // "overlaps", not "covers": nothing here computes paint order,
                // and which of the two is on top is not the point. Two glyphs
                // in one place is the fault whichever wins.
                out.overlaps.push(
                    '#' + SECTIONS[i] + ' "' + a.what + '" overlaps #' + SECTIONS[j] +
                    ' "' + b.what + '" over ' + w + 'x' + h + 'px');
            }
        }
    }
}

// The clock is also T2.2's marker: MainActivity reads #clock out of the DOM on
// load and logs panel=rendered clock="HH:MM:SS". If the id or the format goes,
// that acceptance breaks somewhere far away from here.
const clock = document.getElementById('clock');
out.clockText = clock ? clock.textContent : null;
if (!clock || !/^\d{2}:\d{2}:\d{2}$/.test((clock.textContent || '').trim())) {
    out.outsideViewport.push('#clock is not HH:MM:SS, which breaks T2.2 panel=rendered');
}

return out;
