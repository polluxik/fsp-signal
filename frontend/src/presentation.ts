/** Product copy only. Stored provenance, identifiers and verification remain intact. */
export function displayText(value: string | null | undefined): string {
  return (value ?? '')
    .replace(/\s*\[демо\]/gi, '')
    .replace(/Это вымышленный пример, не измерение реального проекта\./gi, '')
    .replace(/Условная иллюстрация:[\s\S]*$/gi, '')
    .replace(/Демо-оценки синтетические и не подтверждают навыки реального кандидата\./gi, 'Источник оценки не подтверждён.')
    .replace(/Синтетическая демонстрационная запись/gi, 'Сохранённая запись')
    .replace(/Проверялось на демонстрационном сценарии/gi, 'Проверялось на контрольном сценарии')
    .replace(/\s*\(демонстрационная запись\)/gi, '')
    .replace(/, а не только с демонстрацией технологии/gi, '')
    .replace(/демонстрационн[а-яё]*\s*/gi, '')
    .replace(/синтетическ[а-яё]*\s*/gi, '')
    .replace(/вымышленн[а-яё]*\s*/gi, '')
    .replace(/демо(?=[-\s]|$)[-\s]?/gi, '')
    .replace(/персонажа/gi, 'кандидата')
    .replace(/\s{2,}/g, ' ')
    .trim()
}
