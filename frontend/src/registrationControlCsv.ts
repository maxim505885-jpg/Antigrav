export type RegistrationControlCsvRow = {
  label: string;
  source: [string, string, string];
  target: [string, string, string];
};

const REQUIRED_HEADERS = [
  "source_x", "source_y", "source_z", "target_x", "target_y", "target_z",
] as const;

function detectDelimiter(headerLine: string): string {
  const candidates = [",", ";", "\t"];
  let best = ",";
  let bestCount = -1;
  for (const delimiter of candidates) {
    let quoted = false;
    let count = 0;
    for (let index = 0; index < headerLine.length; index += 1) {
      const char = headerLine[index];
      if (char === '"') {
        if (quoted && headerLine[index + 1] === '"') index += 1;
        else quoted = !quoted;
      } else if (!quoted && char === delimiter) {
        count += 1;
      }
    }
    if (count > bestCount) {
      best = delimiter;
      bestCount = count;
    }
  }
  if (bestCount < 1) throw new Error("Не удалось определить разделитель CSV.");
  return best;
}

function parseRows(text: string, delimiter: string): Array<{ fields: string[]; line: number }> {
  const rows: Array<{ fields: string[]; line: number }> = [];
  let fields: string[] = [];
  let field = "";
  let quoted = false;
  let line = 1;
  let rowLine = 1;

  const pushRow = () => {
    fields.push(field);
    if (fields.some((value) => value.trim() !== "")) rows.push({ fields, line: rowLine });
    fields = [];
    field = "";
  };

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
        if (char === "\n") line += 1;
      }
      continue;
    }

    if (char === '"' && field.length === 0) quoted = true;
    else if (char === delimiter) {
      fields.push(field);
      field = "";
    } else if (char === "\r" || char === "\n") {
      pushRow();
      if (char === "\r" && text[index + 1] === "\n") index += 1;
      line += 1;
      rowLine = line;
    } else {
      field += char;
    }
  }

  if (quoted) throw new Error("CSV содержит незакрытую кавычку.");
  if (field.length > 0 || fields.length > 0) pushRow();
  return rows;
}

export function parseRegistrationControlsCsv(text: string): RegistrationControlCsvRow[] {
  const cleanText = text.replace(/^\uFEFF/, "");
  const headerLine = cleanText.split(/\r?\n/).find((line) => line.trim() !== "");
  if (!headerLine) throw new Error("CSV пустой.");

  const delimiter = detectDelimiter(headerLine);
  const rows = parseRows(cleanText, delimiter);
  const headers = rows[0].fields.map((value) => value.trim().toLowerCase());
  const duplicate = headers.find((header, index) => header && headers.indexOf(header) !== index);
  if (duplicate) throw new Error(`Заголовок CSV повторяется: ${duplicate}.`);

  const missing = REQUIRED_HEADERS.filter((header) => !headers.includes(header));
  if (missing.length) {
    throw new Error(`В CSV отсутствуют обязательные заголовки: ${missing.join(", ")}.`);
  }
  const labelIndex = headers.indexOf("label");
  const indices = REQUIRED_HEADERS.map((header) => headers.indexOf(header));
  const controls: RegistrationControlCsvRow[] = [];

  for (const row of rows.slice(1)) {
    if (row.fields.length !== headers.length) {
      throw new Error(`В строке ${row.line} найдено ${row.fields.length} полей вместо ${headers.length}.`);
    }
    const coordinates = indices.map((columnIndex) => {
      const raw = row.fields[columnIndex].trim().replace(/\s+/g, "");
      const normalized = delimiter === ";" ? raw.replace(",", ".") : raw;
      const value = Number(normalized);
      if (!raw || !Number.isFinite(value)) {
        throw new Error(`В строке ${row.line} есть пустая или некорректная координата.`);
      }
      return String(value);
    });
    const label = labelIndex >= 0 ? row.fields[labelIndex].trim() : "";
    controls.push({
      label: label || `Контроль ${controls.length + 1}`,
      source: coordinates.slice(0, 3) as [string, string, string],
      target: coordinates.slice(3, 6) as [string, string, string],
    });
  }

  if (controls.length < 3) throw new Error("Для независимой проверки нужно минимум три контрольные пары.");
  return controls;
}
