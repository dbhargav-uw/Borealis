// Lightweight logger. Info/warn no-op in production builds; errors always surface.
// (Project rule: no raw console.log in production.)

type LogArgs = readonly unknown[]

const isProd: boolean = import.meta.env.PROD

export const logger = {
  info: (...args: LogArgs): void => {
    if (!isProd) console.info(...args)
  },
  warn: (...args: LogArgs): void => {
    if (!isProd) console.warn(...args)
  },
  error: (...args: LogArgs): void => {
    console.error(...args)
  },
}
