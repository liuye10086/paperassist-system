type FileInfo = {id:string; filename:string; file_type:string}

/** A single unambiguous 10x triplet. Duplicated roles need manual selection. */
export function singleCellMtxFiles(files: FileInfo[]) {
  const originals = files.filter(file => file.file_type === 'bio_component')
  const roles = [/^matrix\.mtx(?:\.gz)?$/i, /^(?:features|genes)\.tsv(?:\.gz)?$/i, /^barcodes\.tsv(?:\.gz)?$/i]
  const matches = roles.map(role => originals.filter(file => role.test(file.filename)))
  return matches.every(group => group.length === 1) ? matches.map(group => group[0]) : []
}
