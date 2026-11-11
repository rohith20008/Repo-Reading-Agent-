export class CsvFormatter {
  format(rows: string[][]): string {
    return rows.map((row) => row.join(",")).join("\n");
  }
}
