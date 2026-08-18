/**
 * Every icon this app ships, derived from the one mark.
 *
 * Run after changing `design-guide/mark/flintroom-f.png`:
 *
 *   node scripts/build-icons.mjs && npx expo prebuild -p android
 *
 * **The prebuild is not optional.** `android/` and `ios/` are generated and
 * gitignored, and `expo run:android` does NOT re-derive the launcher resources
 * from `app.json` on its own — it will build and install happily against res
 * files from whenever the directory was last created, so a changed icon simply
 * does not appear and nothing reports a problem.
 *
 * There is no ImageMagick, no `sharp` and no PIL on a plain macOS box, and none
 * of them is worth a dependency for a file that changes once a year. `sips`
 * cannot composite onto transparency. So the PNG codec is here: `node:zlib`
 * does the hard part and the rest is unfiltering scanlines.
 *
 * Only 8-bit non-interlaced PNG is decoded, which is what every export tool
 * produces by default. Anything else throws rather than guessing.
 */

import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { inflateSync, deflateSync } from 'node:zlib';
import { readFileSync, writeFileSync } from 'node:fs';

const SIG = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

function crc32(buf) {
  let c, table = crc32.t;
  if (!table) {
    table = crc32.t = new Int32Array(256);
    for (let n = 0; n < 256; n++) {
      c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      table[n] = c;
    }
  }
  c = -1;
  for (let i = 0; i < buf.length; i++) c = table[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ -1) >>> 0;
}

/** Decode a non-interlaced 8-bit PNG to {w, h, px} where px is RGBA. */
function decode(path) {
  const f = readFileSync(path);
  if (!f.subarray(0, 8).equals(SIG)) throw new Error('not a png');

  let pos = 8, w = 0, h = 0, colour = 0, depth = 0, idat = [], palette = null, trns = null;
  while (pos < f.length) {
    const len = f.readUInt32BE(pos);
    const kind = f.toString('ascii', pos + 4, pos + 8);
    const data = f.subarray(pos + 8, pos + 8 + len);
    if (kind === 'IHDR') {
      w = data.readUInt32BE(0); h = data.readUInt32BE(4);
      depth = data[8]; colour = data[9];
      if (data[12] !== 0) throw new Error('interlaced png unsupported');
      if (depth !== 8) throw new Error(`bit depth ${depth} unsupported`);
    } else if (kind === 'PLTE') palette = Buffer.from(data);
    else if (kind === 'tRNS') trns = Buffer.from(data);
    else if (kind === 'IDAT') idat.push(Buffer.from(data));
    else if (kind === 'IEND') break;
    pos += 12 + len;
  }

  const CH = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }[colour];
  if (!CH) throw new Error(`colour type ${colour} unsupported`);
  const raw = inflateSync(Buffer.concat(idat));
  const stride = w * CH;
  const out = Buffer.alloc(w * h * CH);
  let prev = Buffer.alloc(stride);

  for (let y = 0; y < h; y++) {
    const filter = raw[y * (stride + 1)];
    const line = Buffer.from(raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1)));
    for (let i = 0; i < stride; i++) {
      const a = i >= CH ? line[i - CH] : 0;
      const b = prev[i];
      const c = i >= CH ? prev[i - CH] : 0;
      let v = line[i];
      if (filter === 1) v += a;
      else if (filter === 2) v += b;
      else if (filter === 3) v += (a + b) >> 1;
      else if (filter === 4) {
        const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
        v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      }
      line[i] = v & 0xff;
    }
    line.copy(out, y * stride);
    prev = line;
  }

  // Normalise everything to RGBA.
  const px = Buffer.alloc(w * h * 4);
  for (let i = 0, n = w * h; i < n; i++) {
    let r, g, b, a = 255;
    if (colour === 6) { r = out[i * 4]; g = out[i * 4 + 1]; b = out[i * 4 + 2]; a = out[i * 4 + 3]; }
    else if (colour === 2) { r = out[i * 3]; g = out[i * 3 + 1]; b = out[i * 3 + 2]; }
    else if (colour === 0) { r = g = b = out[i]; }
    else if (colour === 4) { r = g = b = out[i * 2]; a = out[i * 2 + 1]; }
    else { const k = out[i]; r = palette[k * 3]; g = palette[k * 3 + 1]; b = palette[k * 3 + 2]; if (trns && k < trns.length) a = trns[k]; }
    px[i * 4] = r; px[i * 4 + 1] = g; px[i * 4 + 2] = b; px[i * 4 + 3] = a;
  }
  return { w, h, px };
}

function encode(path, { w, h, px }) {
  const stride = w * 4;
  const raw = Buffer.alloc((stride + 1) * h);
  for (let y = 0; y < h; y++) {
    raw[y * (stride + 1)] = 0;
    px.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  }
  const chunk = (kind, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(kind, 'ascii'), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(body));
    return Buffer.concat([len, body, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  writeFileSync(path, Buffer.concat([
    SIG,
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]));
}

/** Box-filter resample. Good for the downscales every icon size here needs. */
function resample(src, w, h) {
  const px = Buffer.alloc(w * h * 4);
  const sx = src.w / w, sy = src.h / h;
  for (let y = 0; y < h; y++) {
    const y0 = Math.floor(y * sy), y1 = Math.max(y0 + 1, Math.floor((y + 1) * sy));
    for (let x = 0; x < w; x++) {
      const x0 = Math.floor(x * sx), x1 = Math.max(x0 + 1, Math.floor((x + 1) * sx));
      let r = 0, g = 0, b = 0, a = 0, n = 0;
      for (let j = y0; j < y1; j++) for (let i = x0; i < x1; i++) {
        const k = (j * src.w + i) * 4, al = src.px[k + 3] / 255;
        // Premultiplied, or a transparent pixel's colour bleeds into the edge.
        r += src.px[k] * al; g += src.px[k + 1] * al; b += src.px[k + 2] * al; a += al; n++;
      }
      const k = (y * w + x) * 4;
      px[k] = a > 0 ? Math.round(r / a) : 0;
      px[k + 1] = a > 0 ? Math.round(g / a) : 0;
      px[k + 2] = a > 0 ? Math.round(b / a) : 0;
      px[k + 3] = Math.round((a / n) * 255);
    }
  }
  return { w, h, px };
}

// --- The icons themselves ------------------------------------------------

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(HERE, '../../design-guide/mark/flintroom-f.png');
const OUT = resolve(HERE, '../assets/images');

const src = decode(SRC);
const GROUND = [239, 243, 244];   // the cool grey the mark was supplied on
const MARK = [203, 70, 1];        // the mark itself
const SURFACE = [252, 249, 248];  // color.surface — the app's own warm ground

// Blue has the widest spread between ground and mark (243 of 255), so it
// recovers coverage with the least quantisation error. Everything else is a
// re-composite of that one number.
const coverage = (k) => Math.min(1, Math.max(0, (GROUND[2] - src.px[k + 2]) / (GROUND[2] - MARK[2])));

/** The mark alone, on transparency, at the size it was supplied. */
const cut = { w: src.w, h: src.h, px: Buffer.alloc(src.w * src.h * 4) };
for (let i = 0; i < src.w * src.h; i++) {
  const k = i * 4, a = coverage(k);
  cut.px[k] = MARK[0]; cut.px[k + 1] = MARK[1]; cut.px[k + 2] = MARK[2];
  cut.px[k + 3] = Math.round(a * 255);
}

// Where the mark actually is, so every derived asset can be positioned against
// the mark rather than against the canvas it happened to arrive on.
let x0 = src.w, y0 = src.h, x1 = -1, y1 = -1;
for (let y = 0; y < src.h; y++) for (let x = 0; x < src.w; x++) {
  if (cut.px[(y * src.w + x) * 4 + 3] > 8) {
    if (x < x0) x0 = x; if (x > x1) x1 = x;
    if (y < y0) y0 = y; if (y > y1) y1 = y;
  }
}
const markW = x1 - x0 + 1, markH = y1 - y0 + 1;
console.log(`mark bbox ${markW}x${markH} at ${x0},${y0}`);

/** Place `img`'s mark bbox centred on a fresh canvas, scaled by `factor`. */
function compose({ size, factor, bg, tint }) {
  const px = Buffer.alloc(size * size * 4);
  if (bg) for (let i = 0; i < size * size; i++) {
    px[i * 4] = bg[0]; px[i * 4 + 1] = bg[1]; px[i * 4 + 2] = bg[2]; px[i * 4 + 3] = 255;
  }
  const dw = Math.round(markW * factor * (size / src.w));
  const dh = Math.round(markH * factor * (size / src.h));
  // Crop to the mark, then resample the crop — resampling the whole canvas and
  // cropping after would blur the edge with the ground it sat on.
  const crop = { w: markW, h: markH, px: Buffer.alloc(markW * markH * 4) };
  for (let y = 0; y < markH; y++)
    cut.px.copy(crop.px, y * markW * 4, ((y + y0) * src.w + x0) * 4, ((y + y0) * src.w + x1 + 1) * 4);
  const small = resample(crop, dw, dh);

  const ox = Math.round((size - dw) / 2), oy = Math.round((size - dh) / 2);
  for (let y = 0; y < dh; y++) for (let x = 0; x < dw; x++) {
    const s = (y * dw + x) * 4, d = ((y + oy) * size + x + ox) * 4;
    const a = small.px[s + 3] / 255;
    if (a === 0) continue;
    const c = tint ?? [small.px[s], small.px[s + 1], small.px[s + 2]];
    if (bg) {
      for (let ch = 0; ch < 3; ch++) px[d + ch] = Math.round(c[ch] * a + bg[ch] * (1 - a));
      px[d + 3] = 255;
    } else {
      px[d] = c[0]; px[d + 1] = c[1]; px[d + 2] = c[2]; px[d + 3] = small.px[s + 3];
    }
  }
  return { w: size, h: size, px };
}

// iOS and the generic icon: opaque, the mark on the app's own warm ground
// rather than the cool grey it was drawn on. `factor` keeps the supplied
// framing — the mark filled 55% of its canvas and still does.
encode(`${OUT}/icon.png`, compose({ size: 1024, factor: 1, bg: SURFACE }));

// Android adaptive foreground. The launcher masks this to a circle, squircle
// or rounded square depending on the device, and only the central 66.6% is
// guaranteed to survive — so the mark is scaled until its bounding box's
// DIAGONAL fits that circle, not its width. Sized at the supplied framing it
// would lose its corners on a round mask.
const SAFE = 1024 * (72 / 108);
const diagonal = Math.hypot(markW, markH);
const fit = (SAFE * 0.95) / diagonal;
console.log(`safe circle ${Math.round(SAFE)}px, mark diagonal ${Math.round(diagonal)}px, scale ${fit.toFixed(3)}`);
encode(`${OUT}/android-icon-foreground.png`, compose({ size: 1024, factor: fit }));

// Themed icons: the launcher recolours this silhouette to the user's wallpaper
// palette, so it must be one flat shape and the brand colour is thrown away.
encode(`${OUT}/android-icon-monochrome.png`, compose({ size: 1024, factor: fit, tint: [0, 0, 0] }));

// The splash draws this over `backgroundColor`, so it stays transparent.
encode(`${OUT}/splash-icon.png`, compose({ size: 1024, factor: 1 }));

encode(`${OUT}/favicon.png`, compose({ size: 48, factor: 1, bg: SURFACE }));

// The mark for use inside the app, cropped to itself rather than centred on a
// square. Every output above is an icon, and an icon is a square with the
// padding an OS expects; a component laying this out wants the glyph's own
// aspect and nothing else, so that a height in points is the height of the
// mark and not of the transparent air around it.
const inApp = { w: markW, h: markH, px: Buffer.alloc(markW * markH * 4) };
for (let y = 0; y < markH; y++)
  cut.px.copy(inApp.px, y * markW * 4, ((y + y0) * src.w + x0) * 4, ((y + y0) * src.w + x1 + 1) * 4);
encode(`${OUT}/mark.png`, resample(inApp, 512, Math.round((512 * markH) / markW)));
console.log(`mark.png at 512x${Math.round((512 * markH) / markW)}`);
console.log('written');
