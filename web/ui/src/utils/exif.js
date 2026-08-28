// ── EXIF date reader ──────────────────────────────────────────
// Ported verbatim from web/static/index.html (lines ~757-889).
// Supports JPEG (APP1/Exif), PNG (eXIf chunk), WebP (EXIF chunk).
// HEIC falls back to server-side extraction via the date picker.

export function extractJpegExif(arr) {
  // Scan for APP1 marker (0xFFE1) containing "Exif\0\0"
  const dv = new DataView(arr.buffer, arr.byteOffset, arr.byteLength);
  const maxScan = Math.min(arr.length, 65536);
  for (let i = 2; i < maxScan - 10; i++) {
    if (dv.getUint16(i) !== 0xFFE1) continue;
    const segLen = dv.getUint16(i + 2);
    if (i + 2 + segLen > arr.length) continue;
    const sig = String.fromCharCode(arr[i+4], arr[i+5], arr[i+6], arr[i+7], arr[i+8], arr[i+9]);
    if (sig !== 'Exif\0\0') continue;
    // Return TIFF data (after "Exif\0\0" header)
    const tiffStart = i + 10;
    const tiffLen = segLen - 8;
    return arr.slice(tiffStart, tiffStart + tiffLen);
  }
  return null;
}

export function extractPngExif(arr) {
  // PNG: 8-byte signature, then chunks: [4B len][4B type][data][4B CRC]
  let offset = 8;
  while (offset + 12 <= arr.length) {
    const dv = new DataView(arr.buffer, arr.byteOffset + offset, 8);
    const len = dv.getUint32(0);
    const type = String.fromCharCode(arr[offset+4], arr[offset+5], arr[offset+6], arr[offset+7]);
    if (type === 'eXIf') {
      return arr.slice(offset + 8, offset + 8 + len);
    }
    if (type === 'IEND') break;
    offset += 12 + len;
  }
  return null;
}

export function extractWebpExif(arr) {
  // RIFF: 'RIFF'[4B size]'WEBP', then chunks: [4B type][4B size][data]
  if (arr.length < 20) return null;
  const type = String.fromCharCode(arr[8], arr[9], arr[10], arr[11]);
  if (type !== 'WEBP') return null;
  let offset = 12;
  while (offset + 8 <= arr.length) {
    const dv = new DataView(arr.buffer, arr.byteOffset + offset, 8);
    const ckType = String.fromCharCode(arr[offset], arr[offset+1], arr[offset+2], arr[offset+3]);
    const ckSize = dv.getUint32(4, true);
    if (ckType === 'EXIF') {
      return arr.slice(offset + 8, offset + 8 + ckSize);
    }
    offset += 8 + ckSize + (ckSize & 1); // chunks are padded to even
  }
  return null;
}

export function parseTiffDate(tiffBytes) {
  // Parse TIFF header + IFD0 to find DateTimeOriginal (0x9003)
  const dv = new DataView(tiffBytes.buffer, tiffBytes.byteOffset, tiffBytes.byteLength);
  if (tiffBytes.length < 8) return null;

  const le = dv.getUint16(0) === 0x4949;  // II = little-endian
  if (dv.getUint16(2, le) !== 0x002A) return null;

  const ifd0Off = dv.getUint32(4, le);
  if (ifd0Off + 2 > tiffBytes.length) return null;

  const numEntries = dv.getUint16(ifd0Off, le);

  for (let j = 0; j < numEntries; j++) {
    const entryOff = ifd0Off + 2 + j * 12;
    if (entryOff + 12 > tiffBytes.length) break;

    const tag = dv.getUint16(entryOff, le);
    if (tag !== 0x9003) continue;  // DateTimeOriginal

    const type = dv.getUint16(entryOff + 2, le);
    const count = dv.getUint32(entryOff + 4, le);
    if (type !== 2) continue;  // Must be ASCII

    let dateBytes;
    if (count <= 4) {
      dateBytes = tiffBytes.slice(entryOff + 8, entryOff + 8 + count);
    } else {
      const valueOff = dv.getUint32(entryOff + 8, le);
      dateBytes = tiffBytes.slice(valueOff, valueOff + count);
    }

    return new TextDecoder('ascii').decode(dateBytes).replace(/\0/g, '').trim();
  }
  return null;
}

export function readExifDate(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = function(e) {
      try {
        const arr = new Uint8Array(e.target.result);
        if (arr.length < 8) { resolve(null); return; }

        let exifBytes = null;

        // JPEG: starts with 0xFFD8
        if (arr[0] === 0xFF && arr[1] === 0xD8) {
          exifBytes = extractJpegExif(arr);
        }
        // PNG: starts with \x89PNG
        else if (arr[0] === 0x89 && arr[1] === 0x50 && arr[2] === 0x4E && arr[3] === 0x47) {
          exifBytes = extractPngExif(arr);
        }
        // WebP: RIFF container
        else if (arr[0] === 0x52 && arr[1] === 0x49 && arr[2] === 0x46 && arr[3] === 0x46) {
          exifBytes = extractWebpExif(arr);
        }
        // HEIC and others: not parsed client-side

        if (exifBytes) {
          const raw = parseTiffDate(exifBytes);
          if (raw && raw.length >= 10) {
            resolve(raw.slice(0, 10).replace(/:/g, '-'));
            return;
          }
        }
        resolve(null);
      } catch {
        resolve(null);
      }
    };
    reader.onerror = () => resolve(null);
    reader.readAsArrayBuffer(file.slice(0, 131072));  // First 128KB is enough for EXIF
  });
}
