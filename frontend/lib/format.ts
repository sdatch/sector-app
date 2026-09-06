export const pct = (x: number, digits = 1) =>
  `${(x * 100).toFixed(digits)}%`;

export const money = (x: number) =>
  x.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });

export const signedMoney = (x: number) => (x < 0 ? `+${money(-x)}` : money(x));

export const num = (x: number, digits = 2) => x.toFixed(digits);
