/** Accountability proof photo: capture, geotag and burn a visible timestamp + location into the image before it is sent. */

export type LocationStatus = 'AVAILABLE' | 'DENIED' | 'UNAVAILABLE';
export type Geo = { status: LocationStatus; latitude?: number; longitude?: number; accuracyM?: number };

/** Best-effort device location. Never blocks the photo: denied or unsupported just means the overlay says so. */
export function getLocation(timeoutMs = 8000): Promise<Geo> {
  if (typeof navigator === 'undefined' || !navigator.geolocation) return Promise.resolve({ status: 'UNAVAILABLE' });
  return new Promise(resolve => {
    navigator.geolocation.getCurrentPosition(
      pos => resolve({ status: 'AVAILABLE', latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracyM: pos.coords.accuracy }),
      err => resolve({ status: err.code === err.PERMISSION_DENIED ? 'DENIED' : 'UNAVAILABLE' }),
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 0 },
    );
  });
}

function coord(value: number, pos: string, neg: string): string {
  return `${Math.abs(value).toFixed(5)}°${value >= 0 ? pos : neg}`;
}

export function locationLine(geo: Geo): string {
  if (geo.status === 'AVAILABLE' && geo.latitude != null && geo.longitude != null) {
    const acc = geo.accuracyM != null ? ` ±${Math.round(geo.accuracyM)}m` : '';
    return `${coord(geo.latitude, 'N', 'S')}, ${coord(geo.longitude, 'E', 'W')}${acc}`;
  }
  if (geo.status === 'DENIED') return 'Location permission denied';
  return 'Location unavailable';
}

/** Draws the photo onto a canvas with a bottom banner burning in the capture time and location, then returns a JPEG blob. */
export function watermark(source: HTMLImageElement, when: Date, geo: Geo, timeZone: string): Promise<Blob> {
  const canvas = document.createElement('canvas');
  canvas.width = source.naturalWidth; canvas.height = source.naturalHeight;
  const ctx = canvas.getContext('2d');
  if (!ctx) return Promise.reject(new Error('Could not prepare the photo'));
  ctx.drawImage(source, 0, 0);

  const whenText = when.toLocaleString('en-IN', { timeZone, dateStyle: 'medium', timeStyle: 'medium' });
  const whereText = locationLine(geo);
  const pad = Math.max(14, Math.round(canvas.width * 0.018));
  const fontSize = Math.max(16, Math.round(canvas.width * 0.028));
  const lineHeight = fontSize * 1.35;
  const bannerHeight = lineHeight * 2 + pad * 1.5;

  ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
  ctx.fillRect(0, canvas.height - bannerHeight, canvas.width, bannerHeight);
  ctx.fillStyle = '#ffffff';
  ctx.font = `600 ${fontSize}px system-ui, sans-serif`;
  ctx.textBaseline = 'middle';
  ctx.fillText(whenText, pad, canvas.height - bannerHeight + pad * 0.75 + lineHeight / 2);
  ctx.font = `400 ${Math.round(fontSize * 0.85)}px system-ui, sans-serif`;
  ctx.fillText(whereText, pad, canvas.height - bannerHeight + pad * 0.75 + lineHeight * 1.5);

  return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Could not prepare the photo')), 'image/jpeg', 0.85));
}

export function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('That file could not be read as a photo'));
    img.src = URL.createObjectURL(file);
  });
}
