/**
 * Has the browser download what an address gives, under a name: the page stays, no tab opens, and a file of the
 * server goes straight to the disk, not through the page.
 */
export function saveUrl(url: string, name: string) {
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}

/** Hands a file the page holds to the browser as a download under its name. */
export function saveFile(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  saveUrl(url, name);
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 30_000);
}
