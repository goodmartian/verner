/** Lower case, no accents: "Córdoba" and "cordoba" are the same word. */
export const fold = (text: string): string =>
  text.trim().toLocaleLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ё/g, 'е');
