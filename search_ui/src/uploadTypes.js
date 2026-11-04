// File extensions the backend accepts on POST /api/upload.
// Keep in sync with uploads.ALLOWED_EXTENSIONS (tests/test_ui_upload.py checks).
export const UPLOAD_EXTENSIONS = [
  '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.wma',
  '.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v',
];

export const UPLOAD_ACCEPT = UPLOAD_EXTENSIONS.join(',');

export const isAllowedUpload = (filename) => {
  const dot = (filename || '').lastIndexOf('.');
  return dot >= 0 && UPLOAD_EXTENSIONS.includes(filename.slice(dot).toLowerCase());
};

// "my talk.final.mp4" -> "my talk.final", used as the default record label.
export const labelFromFilename = (filename) => {
  const dot = (filename || '').lastIndexOf('.');
  return (dot > 0 ? filename.slice(0, dot) : filename || '').trim();
};

export const formatBytes = (n) => {
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
};
