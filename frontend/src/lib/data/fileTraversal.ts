// Turns whatever the browser handed us (dropped files, a dropped folder, or
// an <input webkitdirectory> selection) into a flat {file, relativePath}[]
// -- the shape the upload queue streams one request per entry from.

export interface FlatFile {
  file: File
  relativePath: string
}

async function readEntry(entry: FileSystemEntry, prefix: string, out: FlatFile[]): Promise<void> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) =>
      (entry as FileSystemFileEntry).file(resolve, reject),
    )
    out.push({ file, relativePath: prefix + entry.name })
    return
  }
  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader()
    const children: FileSystemEntry[] = []
    // readEntries() returns results in batches (spec caps ~100/call) and
    // must be called repeatedly until it yields an empty array.
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
        reader.readEntries(resolve, reject),
      )
      if (batch.length === 0) break
      children.push(...batch)
    }
    for (const child of children) await readEntry(child, `${prefix}${entry.name}/`, out)
  }
}

/** Recursively expands a drag-and-drop payload, including dropped folders. */
export async function filesFromDataTransfer(dt: DataTransfer): Promise<FlatFile[]> {
  const items = Array.from(dt.items)
  const entries = items
    .map((item) => item.webkitGetAsEntry?.())
    .filter((e): e is FileSystemEntry => e != null)

  if (entries.length === 0) {
    // Fallback for browsers without webkitGetAsEntry: flat files only.
    return Array.from(dt.files).map((file) => ({ file, relativePath: file.name }))
  }

  const out: FlatFile[] = []
  for (const entry of entries) await readEntry(entry, '', out)
  return out
}

/** Flattens a <input type="file" [webkitdirectory] multiple> selection. */
export function filesFromFileList(list: FileList): FlatFile[] {
  return Array.from(list).map((file) => ({
    file,
    relativePath: file.webkitRelativePath || file.name,
  }))
}

/** A sensible default dataset name for a batch: its common top folder, or the lone filename. */
export function inferDatasetName(files: FlatFile[]): string {
  if (files.length === 0) return 'Untitled'
  if (files.length === 1) return files[0].file.name
  const top = files[0].relativePath.split('/')[0]
  return top && files.every((f) => f.relativePath.startsWith(`${top}/`)) ? top : `${files.length} files`
}
