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
//
// T6.11 found two more of the same shape, both in `ink` below: a ::before has
// no DOM node, and the walk started at a section's descendants rather than at
// the section. Between them that made the clock, the date, the stale badge
// and all four card titles invisible to the overlap check -- in the file
// whose entire purpose is to catch two things drawn in one place.

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
    scrolling: [],
    pointlessMotion: [],
};

// What is actually on the glass, which is not the same thing as what the
// layout says.
//
// Questions 2 and 4 both claim to be about what is drawn -- "one card escaped",
// "some of it is underneath the rest" -- and until T6.6 nothing on this panel
// could tell the two apart, because no card had ever held more than it could
// show in either fixture. A scrolling card does, by design: its rows below the
// fold are laid out past the card's bottom edge and clipped away, and as the
// card walks up through them the ones above the top edge are clipped too.
// getBoundingClientRect describes those boxes honestly and uselessly. Left
// alone, every hidden row reads as a section escaping the viewport and as ink
// sitting on top of the card below -- a hundred failures about pixels nobody
// can see.
//
// So a rect inside a scrolling card is intersected with the boxes that clip it
// before it is judged.
//
// Scoped to `[data-scroll]`, and not applied to the panel at large, which was
// the first cut. Clipping every rect against every `overflow: hidden` ancestor
// is more honest in the abstract and quietly guts question 2: `body` and
// `#panel` both clip, so a card that escaped the panel would be intersected
// back inside it and reported as fine. The one thing that changed in T6.6 is
// that a card can now hold rows outside its own box on purpose, and that is
// the one case this handles. Everything else measures exactly what it measured
// before.
//
// Nothing here weakens question 3 either: whether a section's content fits
// inside it is measured separately, per section, from scrollHeight -- a card
// quietly eating its own rows still fails, and a card that says `data-scroll`
// with nothing hidden fails too.
//
// One blind spot, named because it is not obvious and there is no instance of
// it today. This assumes every clipping ancestor between the element and the
// scrolling section actually clips it, which is false for an absolutely
// positioned descendant whose containing block is outside that ancestor: such
// an element paints outside the card and would be intersected back inside it
// and reported as fine. Nothing in either theme is positioned inside a list
// card -- but #battery is exactly that kind of element elsewhere on the panel,
// and it is the fault that earned question 4 in the first place (T5.4). A
// future "+3 more" badge pinned inside a scrolling card is the shape to watch
// for.
function paintedRect(el) {
    let r = el.getBoundingClientRect();
    const scope = el.parentElement && el.parentElement.closest('[data-scroll]');
    if (!scope) {
        return r;
    }
    for (let a = el.parentElement; a; a = a.parentElement) {
        const style = getComputedStyle(a);
        if (style.overflowX !== 'visible' || style.overflowY !== 'visible') {
            const c = a.getBoundingClientRect();
            r = {
                top: Math.max(r.top, c.top),
                left: Math.max(r.left, c.left),
                bottom: Math.min(r.bottom, c.bottom),
                right: Math.min(r.right, c.right),
            };
            r.width = Math.max(0, r.right - r.left);
            r.height = Math.max(0, r.bottom - r.top);
            if (!r.width || !r.height) {
                return r;
            }
        }
        if (a === scope) {
            break;
        }
    }
    return r;
}

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
    //
    // Unless the theme said it was not. A section carrying `data-scroll` holds
    // more rows than it can show and is walking through them (T6.6), which is
    // the answer to this fault rather than an instance of it. Both directions
    // are checked, and they are not the same check:
    //
    //   - a section that overflows without the attribute is the old fault, and
    //     it is still a failure,
    //   - a section with the attribute and nothing hidden is motion for its own
    //     sake on a panel in someone's peripheral vision (T6.6 step 2), and is
    //     also a failure,
    //   - a section with both is reported separately, so a pass can *require*
    //     it and this harness can say something about the feature rather than
    //     only about the absence of faults.
    //
    // The overflow of a scrolling card is not measurable on the section: the
    // rows are two boxes down, inside the window that clips them, and the
    // section's own content fits it exactly. overflowInside() finds it without
    // being told the theme's class names -- any element taller than the parent
    // that clips it.
    const declared = el.hasAttribute('data-scroll');
    const inside = overflowInside(el);
    if (declared) {
        if (inside.tall) {
            out.scrolling.push('#' + id + ' ' + inside.tall);
        } else {
            out.pointlessMotion.push(
                '#' + id + ' is marked data-scroll and nothing is hidden');
        }
    } else if (el.scrollHeight > el.clientHeight + 0.5 || inside.tall) {
        out.clippedContent.push(
            '#' + id + ' content ' + el.scrollWidth + 'x' + el.scrollHeight +
            ' in a box of ' + el.clientWidth + 'x' + el.clientHeight +
            (inside.tall ? '; ' + inside.tall : ''));
    }

    // Width is checked the same way whichever it is. `data-scroll` is a promise
    // about a *vertical* scroll and excuses nothing sideways -- a card too
    // narrow for its rows hides them for good, moving or not.
    if (el.scrollWidth > el.clientWidth + 0.5 || inside.wide) {
        out.clippedContent.push('#' + id + ' ' + (inside.wide
            || ('content is ' + el.scrollWidth + 'px wide in a ' + el.clientWidth
                + 'px box')));
    }
}

// The worst thing inside `section` that its own clipping parent cannot show,
// in each axis, as a sentence -- {tall, wide}, either of them null.
//
// A section's scrollHeight used to be enough, and stopped being when T6.6 put
// the rows two boxes down: a nested `overflow: hidden` clips its descendants'
// contribution, so a card whose rows do not fit its inner window measures as
// fitting itself. This walks down and asks the question where it can still be
// answered -- any element bigger than the parent that clips it -- and it does
// so without being told one theme's class names.
//
// Elements only, so a nowrap label ellipsising its own *text* is not a finding:
// that is the label doing its job, and it has no element child to measure.
function overflowInside(section) {
    let tall = null;
    let wide = null;
    section.querySelectorAll('*').forEach((node) => {
        const parent = node.parentElement;
        if (!parent) {
            return;
        }
        const style = getComputedStyle(parent);
        if (style.overflowY !== 'visible') {
            const over = node.offsetHeight - parent.clientHeight;
            if (over > 0.5 && (!tall || over > tall.over)) {
                tall = { over: over, node: node, parent: parent };
            }
        }
        if (style.overflowX !== 'visible') {
            const over = node.offsetWidth - parent.clientWidth;
            if (over > 0.5 && (!wide || over > wide.over)) {
                wide = { over: over, node: node, parent: parent };
            }
        }
    });
    return {
        tall: tall && ('holds ' + tall.node.offsetHeight + 'px of rows in a '
                       + tall.parent.clientHeight + 'px window: '
                       + Math.round(tall.over) + 'px of them are out of sight'),
        wide: wide && ('holds a ' + wide.node.offsetWidth + 'px box in a '
                       + wide.parent.clientWidth + 'px one: '
                       + Math.round(wide.over) + 'px of it is cut off sideways'),
    };
}

// Not just the five sections: any descendant can escape, and a row sticking out
// of a card is as broken as a card sticking out of the page.
document.querySelectorAll('body *').forEach((el) => {
    const r = paintedRect(el);
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
// A ::before's ink, or null when the element has none.
//
// **The harness could not see a card title until T6.11**, and the gap is the
// kind this file exists to close: the four card headings are pseudo elements,
// pseudo elements have no DOM node, and `querySelectorAll('*')` below has
// therefore never been shown one. It did not matter while the words were
// written in the stylesheet and never changed. It matters the moment they
// come from a language table -- DESATUALIZADO, the first pt-BR word tried for
// the stale badge, landed squarely on top of TEMPO and this file reported the
// pass as clean.
//
// There is no geometry API for a pseudo element, so the text is measured with
// a probe: a span carrying the same computed font, size, weight, spacing and
// transform, laid out absolutely so it disturbs nothing, measured, removed.
// That gives the width exactly. The rest of the box is the element's own
// content box -- the title is the first flex item in its card, so it starts at
// the content top -- and the line height the pseudo computes.
//
// The probe is appended to the element it is measuring rather than to <body>,
// because `font` and `letter-spacing` can be inherited and a probe elsewhere
// in the tree would inherit somebody else's.
function pseudoInk(el) {
    const style = getComputedStyle(el, '::before');
    const content = style.content;
    if (!content || content === 'none' || content === 'normal') {
        return null;
    }
    // The computed value of `content: attr(data-title)` is the resolved
    // string, quoted. Anything else -- a counter, an image -- is not text this
    // panel draws and is left alone.
    const text = /^"([\s\S]*)"$/.test(content) ? content.slice(1, -1) : '';
    if (!text.trim()) {
        return null;
    }

    const probe = document.createElement('span');
    probe.textContent = text;
    probe.style.position = 'absolute';
    probe.style.visibility = 'hidden';
    probe.style.whiteSpace = 'pre';
    // The longhands, not the `font` shorthand: Firefox computes `font` to the
    // empty string on a pseudo element, so setting it copies nothing and the
    // probe measures the text in whatever the document's default face is --
    // which is a width, so nothing throws and the answer is quietly wrong.
    probe.style.fontStyle = style.fontStyle;
    probe.style.fontWeight = style.fontWeight;
    probe.style.fontSize = style.fontSize;
    probe.style.fontFamily = style.fontFamily;
    probe.style.letterSpacing = style.letterSpacing;
    probe.style.textTransform = style.textTransform;
    el.appendChild(probe);
    const width = probe.getBoundingClientRect().width;
    probe.remove();
    if (width < 0.5) {
        return null;
    }

    const box = el.getBoundingClientRect();
    const own = getComputedStyle(el);
    const left = box.left + parseFloat(own.borderLeftWidth) + parseFloat(own.paddingLeft);
    const top = box.top + parseFloat(own.borderTopWidth) + parseFloat(own.paddingTop);
    const height = parseFloat(style.lineHeight) || parseFloat(style.fontSize);
    return {
        r: { left: left, top: top, right: left + width, bottom: top + height,
             width: width, height: height },
        what: text.slice(0, 24),
    };
}

function ink(root) {
    const found = [];
    // **The root itself is in the list, and it was not until T6.11.** The
    // walk below was `root.querySelectorAll('*')`, which is every *descendant*
    // -- so a section whose text sits directly on the section element, with no
    // child to carry it, contributed no ink at all. Three of the eight
    // sections are like that: #clock, #date and #stale-badge. The overlap
    // check has therefore never been able to see the clock, the date, or the
    // badge collide with anything, in a file whose entire purpose is to catch
    // exactly that -- and it was found by trying a thirteen-letter Portuguese
    // word for STALE, watching it land on top of the weather card's title,
    // and being told the pass was clean.
    //
    // Document order is kept, because the report reads better when a
    // collision names the two things in the order somebody would look for
    // them.
    [root].concat(Array.from(root.querySelectorAll('*'))).forEach((el) => {
        const pseudo = pseudoInk(el);
        if (pseudo) {
            found.push(pseudo);
        }
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
        const r = paintedRect(el);
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
