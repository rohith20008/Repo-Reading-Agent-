import { CsvFormatter } from "./csvFormatter";

export class ReportService {
  constructor(private readonly formatter: CsvFormatter) {}

  generate(rows: string[][]): string {
    return this.formatter.format(rows);
  }
}
