
/**
 * Client
**/

import * as runtime from './runtime/library.js';
import $Types = runtime.Types // general types
import $Public = runtime.Types.Public
import $Utils = runtime.Types.Utils
import $Extensions = runtime.Types.Extensions
import $Result = runtime.Types.Result

export type PrismaPromise<T> = $Public.PrismaPromise<T>


/**
 * Model Benchmark
 * 
 */
export type Benchmark = $Result.DefaultSelection<Prisma.$BenchmarkPayload>

/**
 * ##  Prisma Client ʲˢ
 *
 * Type-safe database client for TypeScript & Node.js
 * @example
 * ```
 * const prisma = new PrismaClient()
 * // Fetch zero or more Benchmarks
 * const benchmarks = await prisma.benchmark.findMany()
 * ```
 *
 *
 * Read more in our [docs](https://www.prisma.io/docs/reference/tools-and-interfaces/prisma-client).
 */
export class PrismaClient<
  ClientOptions extends Prisma.PrismaClientOptions = Prisma.PrismaClientOptions,
  const U = 'log' extends keyof ClientOptions ? ClientOptions['log'] extends Array<Prisma.LogLevel | Prisma.LogDefinition> ? Prisma.GetEvents<ClientOptions['log']> : never : never,
  ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs
> {
  [K: symbol]: { types: Prisma.TypeMap<ExtArgs>['other'] }

    /**
   * ##  Prisma Client ʲˢ
   *
   * Type-safe database client for TypeScript & Node.js
   * @example
   * ```
   * const prisma = new PrismaClient()
   * // Fetch zero or more Benchmarks
   * const benchmarks = await prisma.benchmark.findMany()
   * ```
   *
   *
   * Read more in our [docs](https://www.prisma.io/docs/reference/tools-and-interfaces/prisma-client).
   */

  constructor(optionsArg ?: Prisma.Subset<ClientOptions, Prisma.PrismaClientOptions>);
  $on<V extends U>(eventType: V, callback: (event: V extends 'query' ? Prisma.QueryEvent : Prisma.LogEvent) => void): PrismaClient;

  /**
   * Connect with the database
   */
  $connect(): $Utils.JsPromise<void>;

  /**
   * Disconnect from the database
   */
  $disconnect(): $Utils.JsPromise<void>;

/**
   * Executes a prepared raw query and returns the number of affected rows.
   * @example
   * ```
   * const result = await prisma.$executeRaw`UPDATE User SET cool = ${true} WHERE email = ${'user@email.com'};`
   * ```
   *
   * Read more in our [docs](https://www.prisma.io/docs/reference/tools-and-interfaces/prisma-client/raw-database-access).
   */
  $executeRaw<T = unknown>(query: TemplateStringsArray | Prisma.Sql, ...values: any[]): Prisma.PrismaPromise<number>;

  /**
   * Executes a raw query and returns the number of affected rows.
   * Susceptible to SQL injections, see documentation.
   * @example
   * ```
   * const result = await prisma.$executeRawUnsafe('UPDATE User SET cool = $1 WHERE email = $2 ;', true, 'user@email.com')
   * ```
   *
   * Read more in our [docs](https://www.prisma.io/docs/reference/tools-and-interfaces/prisma-client/raw-database-access).
   */
  $executeRawUnsafe<T = unknown>(query: string, ...values: any[]): Prisma.PrismaPromise<number>;

  /**
   * Performs a prepared raw query and returns the `SELECT` data.
   * @example
   * ```
   * const result = await prisma.$queryRaw`SELECT * FROM User WHERE id = ${1} OR email = ${'user@email.com'};`
   * ```
   *
   * Read more in our [docs](https://www.prisma.io/docs/reference/tools-and-interfaces/prisma-client/raw-database-access).
   */
  $queryRaw<T = unknown>(query: TemplateStringsArray | Prisma.Sql, ...values: any[]): Prisma.PrismaPromise<T>;

  /**
   * Performs a raw query and returns the `SELECT` data.
   * Susceptible to SQL injections, see documentation.
   * @example
   * ```
   * const result = await prisma.$queryRawUnsafe('SELECT * FROM User WHERE id = $1 OR email = $2;', 1, 'user@email.com')
   * ```
   *
   * Read more in our [docs](https://www.prisma.io/docs/reference/tools-and-interfaces/prisma-client/raw-database-access).
   */
  $queryRawUnsafe<T = unknown>(query: string, ...values: any[]): Prisma.PrismaPromise<T>;


  /**
   * Allows the running of a sequence of read/write operations that are guaranteed to either succeed or fail as a whole.
   * @example
   * ```
   * const [george, bob, alice] = await prisma.$transaction([
   *   prisma.user.create({ data: { name: 'George' } }),
   *   prisma.user.create({ data: { name: 'Bob' } }),
   *   prisma.user.create({ data: { name: 'Alice' } }),
   * ])
   * ```
   * 
   * Read more in our [docs](https://www.prisma.io/docs/concepts/components/prisma-client/transactions).
   */
  $transaction<P extends Prisma.PrismaPromise<any>[]>(arg: [...P], options?: { isolationLevel?: Prisma.TransactionIsolationLevel }): $Utils.JsPromise<runtime.Types.Utils.UnwrapTuple<P>>

  $transaction<R>(fn: (prisma: Omit<PrismaClient, runtime.ITXClientDenyList>) => $Utils.JsPromise<R>, options?: { maxWait?: number, timeout?: number, isolationLevel?: Prisma.TransactionIsolationLevel }): $Utils.JsPromise<R>


  $extends: $Extensions.ExtendsHook<"extends", Prisma.TypeMapCb<ClientOptions>, ExtArgs, $Utils.Call<Prisma.TypeMapCb<ClientOptions>, {
    extArgs: ExtArgs
  }>>

      /**
   * `prisma.benchmark`: Exposes CRUD operations for the **Benchmark** model.
    * Example usage:
    * ```ts
    * // Fetch zero or more Benchmarks
    * const benchmarks = await prisma.benchmark.findMany()
    * ```
    */
  get benchmark(): Prisma.BenchmarkDelegate<ExtArgs, ClientOptions>;
}

export namespace Prisma {
  export import DMMF = runtime.DMMF

  export type PrismaPromise<T> = $Public.PrismaPromise<T>

  /**
   * Validator
   */
  export import validator = runtime.Public.validator

  /**
   * Prisma Errors
   */
  export import PrismaClientKnownRequestError = runtime.PrismaClientKnownRequestError
  export import PrismaClientUnknownRequestError = runtime.PrismaClientUnknownRequestError
  export import PrismaClientRustPanicError = runtime.PrismaClientRustPanicError
  export import PrismaClientInitializationError = runtime.PrismaClientInitializationError
  export import PrismaClientValidationError = runtime.PrismaClientValidationError

  /**
   * Re-export of sql-template-tag
   */
  export import sql = runtime.sqltag
  export import empty = runtime.empty
  export import join = runtime.join
  export import raw = runtime.raw
  export import Sql = runtime.Sql



  /**
   * Decimal.js
   */
  export import Decimal = runtime.Decimal

  export type DecimalJsLike = runtime.DecimalJsLike

  /**
   * Metrics
   */
  export type Metrics = runtime.Metrics
  export type Metric<T> = runtime.Metric<T>
  export type MetricHistogram = runtime.MetricHistogram
  export type MetricHistogramBucket = runtime.MetricHistogramBucket

  /**
  * Extensions
  */
  export import Extension = $Extensions.UserArgs
  export import getExtensionContext = runtime.Extensions.getExtensionContext
  export import Args = $Public.Args
  export import Payload = $Public.Payload
  export import Result = $Public.Result
  export import Exact = $Public.Exact

  /**
   * Prisma Client JS version: 6.16.3
   * Query Engine version: bb420e667c1820a8c05a38023385f6cc7ef8e83a
   */
  export type PrismaVersion = {
    client: string
  }

  export const prismaVersion: PrismaVersion

  /**
   * Utility Types
   */


  export import JsonObject = runtime.JsonObject
  export import JsonArray = runtime.JsonArray
  export import JsonValue = runtime.JsonValue
  export import InputJsonObject = runtime.InputJsonObject
  export import InputJsonArray = runtime.InputJsonArray
  export import InputJsonValue = runtime.InputJsonValue

  /**
   * Types of the values used to represent different kinds of `null` values when working with JSON fields.
   *
   * @see https://www.prisma.io/docs/concepts/components/prisma-client/working-with-fields/working-with-json-fields#filtering-on-a-json-field
   */
  namespace NullTypes {
    /**
    * Type of `Prisma.DbNull`.
    *
    * You cannot use other instances of this class. Please use the `Prisma.DbNull` value.
    *
    * @see https://www.prisma.io/docs/concepts/components/prisma-client/working-with-fields/working-with-json-fields#filtering-on-a-json-field
    */
    class DbNull {
      private DbNull: never
      private constructor()
    }

    /**
    * Type of `Prisma.JsonNull`.
    *
    * You cannot use other instances of this class. Please use the `Prisma.JsonNull` value.
    *
    * @see https://www.prisma.io/docs/concepts/components/prisma-client/working-with-fields/working-with-json-fields#filtering-on-a-json-field
    */
    class JsonNull {
      private JsonNull: never
      private constructor()
    }

    /**
    * Type of `Prisma.AnyNull`.
    *
    * You cannot use other instances of this class. Please use the `Prisma.AnyNull` value.
    *
    * @see https://www.prisma.io/docs/concepts/components/prisma-client/working-with-fields/working-with-json-fields#filtering-on-a-json-field
    */
    class AnyNull {
      private AnyNull: never
      private constructor()
    }
  }

  /**
   * Helper for filtering JSON entries that have `null` on the database (empty on the db)
   *
   * @see https://www.prisma.io/docs/concepts/components/prisma-client/working-with-fields/working-with-json-fields#filtering-on-a-json-field
   */
  export const DbNull: NullTypes.DbNull

  /**
   * Helper for filtering JSON entries that have JSON `null` values (not empty on the db)
   *
   * @see https://www.prisma.io/docs/concepts/components/prisma-client/working-with-fields/working-with-json-fields#filtering-on-a-json-field
   */
  export const JsonNull: NullTypes.JsonNull

  /**
   * Helper for filtering JSON entries that are `Prisma.DbNull` or `Prisma.JsonNull`
   *
   * @see https://www.prisma.io/docs/concepts/components/prisma-client/working-with-fields/working-with-json-fields#filtering-on-a-json-field
   */
  export const AnyNull: NullTypes.AnyNull

  type SelectAndInclude = {
    select: any
    include: any
  }

  type SelectAndOmit = {
    select: any
    omit: any
  }

  /**
   * Get the type of the value, that the Promise holds.
   */
  export type PromiseType<T extends PromiseLike<any>> = T extends PromiseLike<infer U> ? U : T;

  /**
   * Get the return type of a function which returns a Promise.
   */
  export type PromiseReturnType<T extends (...args: any) => $Utils.JsPromise<any>> = PromiseType<ReturnType<T>>

  /**
   * From T, pick a set of properties whose keys are in the union K
   */
  type Prisma__Pick<T, K extends keyof T> = {
      [P in K]: T[P];
  };


  export type Enumerable<T> = T | Array<T>;

  export type RequiredKeys<T> = {
    [K in keyof T]-?: {} extends Prisma__Pick<T, K> ? never : K
  }[keyof T]

  export type TruthyKeys<T> = keyof {
    [K in keyof T as T[K] extends false | undefined | null ? never : K]: K
  }

  export type TrueKeys<T> = TruthyKeys<Prisma__Pick<T, RequiredKeys<T>>>

  /**
   * Subset
   * @desc From `T` pick properties that exist in `U`. Simple version of Intersection
   */
  export type Subset<T, U> = {
    [key in keyof T]: key extends keyof U ? T[key] : never;
  };

  /**
   * SelectSubset
   * @desc From `T` pick properties that exist in `U`. Simple version of Intersection.
   * Additionally, it validates, if both select and include are present. If the case, it errors.
   */
  export type SelectSubset<T, U> = {
    [key in keyof T]: key extends keyof U ? T[key] : never
  } &
    (T extends SelectAndInclude
      ? 'Please either choose `select` or `include`.'
      : T extends SelectAndOmit
        ? 'Please either choose `select` or `omit`.'
        : {})

  /**
   * Subset + Intersection
   * @desc From `T` pick properties that exist in `U` and intersect `K`
   */
  export type SubsetIntersection<T, U, K> = {
    [key in keyof T]: key extends keyof U ? T[key] : never
  } &
    K

  type Without<T, U> = { [P in Exclude<keyof T, keyof U>]?: never };

  /**
   * XOR is needed to have a real mutually exclusive union type
   * https://stackoverflow.com/questions/42123407/does-typescript-support-mutually-exclusive-types
   */
  type XOR<T, U> =
    T extends object ?
    U extends object ?
      (Without<T, U> & U) | (Without<U, T> & T)
    : U : T


  /**
   * Is T a Record?
   */
  type IsObject<T extends any> = T extends Array<any>
  ? False
  : T extends Date
  ? False
  : T extends Uint8Array
  ? False
  : T extends BigInt
  ? False
  : T extends object
  ? True
  : False


  /**
   * If it's T[], return T
   */
  export type UnEnumerate<T extends unknown> = T extends Array<infer U> ? U : T

  /**
   * From ts-toolbelt
   */

  type __Either<O extends object, K extends Key> = Omit<O, K> &
    {
      // Merge all but K
      [P in K]: Prisma__Pick<O, P & keyof O> // With K possibilities
    }[K]

  type EitherStrict<O extends object, K extends Key> = Strict<__Either<O, K>>

  type EitherLoose<O extends object, K extends Key> = ComputeRaw<__Either<O, K>>

  type _Either<
    O extends object,
    K extends Key,
    strict extends Boolean
  > = {
    1: EitherStrict<O, K>
    0: EitherLoose<O, K>
  }[strict]

  type Either<
    O extends object,
    K extends Key,
    strict extends Boolean = 1
  > = O extends unknown ? _Either<O, K, strict> : never

  export type Union = any

  type PatchUndefined<O extends object, O1 extends object> = {
    [K in keyof O]: O[K] extends undefined ? At<O1, K> : O[K]
  } & {}

  /** Helper Types for "Merge" **/
  export type IntersectOf<U extends Union> = (
    U extends unknown ? (k: U) => void : never
  ) extends (k: infer I) => void
    ? I
    : never

  export type Overwrite<O extends object, O1 extends object> = {
      [K in keyof O]: K extends keyof O1 ? O1[K] : O[K];
  } & {};

  type _Merge<U extends object> = IntersectOf<Overwrite<U, {
      [K in keyof U]-?: At<U, K>;
  }>>;

  type Key = string | number | symbol;
  type AtBasic<O extends object, K extends Key> = K extends keyof O ? O[K] : never;
  type AtStrict<O extends object, K extends Key> = O[K & keyof O];
  type AtLoose<O extends object, K extends Key> = O extends unknown ? AtStrict<O, K> : never;
  export type At<O extends object, K extends Key, strict extends Boolean = 1> = {
      1: AtStrict<O, K>;
      0: AtLoose<O, K>;
  }[strict];

  export type ComputeRaw<A extends any> = A extends Function ? A : {
    [K in keyof A]: A[K];
  } & {};

  export type OptionalFlat<O> = {
    [K in keyof O]?: O[K];
  } & {};

  type _Record<K extends keyof any, T> = {
    [P in K]: T;
  };

  // cause typescript not to expand types and preserve names
  type NoExpand<T> = T extends unknown ? T : never;

  // this type assumes the passed object is entirely optional
  type AtLeast<O extends object, K extends string> = NoExpand<
    O extends unknown
    ? | (K extends keyof O ? { [P in K]: O[P] } & O : O)
      | {[P in keyof O as P extends K ? P : never]-?: O[P]} & O
    : never>;

  type _Strict<U, _U = U> = U extends unknown ? U & OptionalFlat<_Record<Exclude<Keys<_U>, keyof U>, never>> : never;

  export type Strict<U extends object> = ComputeRaw<_Strict<U>>;
  /** End Helper Types for "Merge" **/

  export type Merge<U extends object> = ComputeRaw<_Merge<Strict<U>>>;

  /**
  A [[Boolean]]
  */
  export type Boolean = True | False

  // /**
  // 1
  // */
  export type True = 1

  /**
  0
  */
  export type False = 0

  export type Not<B extends Boolean> = {
    0: 1
    1: 0
  }[B]

  export type Extends<A1 extends any, A2 extends any> = [A1] extends [never]
    ? 0 // anything `never` is false
    : A1 extends A2
    ? 1
    : 0

  export type Has<U extends Union, U1 extends Union> = Not<
    Extends<Exclude<U1, U>, U1>
  >

  export type Or<B1 extends Boolean, B2 extends Boolean> = {
    0: {
      0: 0
      1: 1
    }
    1: {
      0: 1
      1: 1
    }
  }[B1][B2]

  export type Keys<U extends Union> = U extends unknown ? keyof U : never

  type Cast<A, B> = A extends B ? A : B;

  export const type: unique symbol;



  /**
   * Used by group by
   */

  export type GetScalarType<T, O> = O extends object ? {
    [P in keyof T]: P extends keyof O
      ? O[P]
      : never
  } : never

  type FieldPaths<
    T,
    U = Omit<T, '_avg' | '_sum' | '_count' | '_min' | '_max'>
  > = IsObject<T> extends True ? U : T

  type GetHavingFields<T> = {
    [K in keyof T]: Or<
      Or<Extends<'OR', K>, Extends<'AND', K>>,
      Extends<'NOT', K>
    > extends True
      ? // infer is only needed to not hit TS limit
        // based on the brilliant idea of Pierre-Antoine Mills
        // https://github.com/microsoft/TypeScript/issues/30188#issuecomment-478938437
        T[K] extends infer TK
        ? GetHavingFields<UnEnumerate<TK> extends object ? Merge<UnEnumerate<TK>> : never>
        : never
      : {} extends FieldPaths<T[K]>
      ? never
      : K
  }[keyof T]

  /**
   * Convert tuple to union
   */
  type _TupleToUnion<T> = T extends (infer E)[] ? E : never
  type TupleToUnion<K extends readonly any[]> = _TupleToUnion<K>
  type MaybeTupleToUnion<T> = T extends any[] ? TupleToUnion<T> : T

  /**
   * Like `Pick`, but additionally can also accept an array of keys
   */
  type PickEnumerable<T, K extends Enumerable<keyof T> | keyof T> = Prisma__Pick<T, MaybeTupleToUnion<K>>

  /**
   * Exclude all keys with underscores
   */
  type ExcludeUnderscoreKeys<T extends string> = T extends `_${string}` ? never : T


  export type FieldRef<Model, FieldType> = runtime.FieldRef<Model, FieldType>

  type FieldRefInputType<Model, FieldType> = Model extends never ? never : FieldRef<Model, FieldType>


  export const ModelName: {
    Benchmark: 'Benchmark'
  };

  export type ModelName = (typeof ModelName)[keyof typeof ModelName]


  export type Datasources = {
    db?: Datasource
  }

  interface TypeMapCb<ClientOptions = {}> extends $Utils.Fn<{extArgs: $Extensions.InternalArgs }, $Utils.Record<string, any>> {
    returns: Prisma.TypeMap<this['params']['extArgs'], ClientOptions extends { omit: infer OmitOptions } ? OmitOptions : {}>
  }

  export type TypeMap<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs, GlobalOmitOptions = {}> = {
    globalOmitOptions: {
      omit: GlobalOmitOptions
    }
    meta: {
      modelProps: "benchmark"
      txIsolationLevel: Prisma.TransactionIsolationLevel
    }
    model: {
      Benchmark: {
        payload: Prisma.$BenchmarkPayload<ExtArgs>
        fields: Prisma.BenchmarkFieldRefs
        operations: {
          findUnique: {
            args: Prisma.BenchmarkFindUniqueArgs<ExtArgs>
            result: $Utils.PayloadToResult<Prisma.$BenchmarkPayload> | null
          }
          findUniqueOrThrow: {
            args: Prisma.BenchmarkFindUniqueOrThrowArgs<ExtArgs>
            result: $Utils.PayloadToResult<Prisma.$BenchmarkPayload>
          }
          findFirst: {
            args: Prisma.BenchmarkFindFirstArgs<ExtArgs>
            result: $Utils.PayloadToResult<Prisma.$BenchmarkPayload> | null
          }
          findFirstOrThrow: {
            args: Prisma.BenchmarkFindFirstOrThrowArgs<ExtArgs>
            result: $Utils.PayloadToResult<Prisma.$BenchmarkPayload>
          }
          findMany: {
            args: Prisma.BenchmarkFindManyArgs<ExtArgs>
            result: $Utils.PayloadToResult<Prisma.$BenchmarkPayload>[]
          }
          create: {
            args: Prisma.BenchmarkCreateArgs<ExtArgs>
            result: $Utils.PayloadToResult<Prisma.$BenchmarkPayload>
          }
          createMany: {
            args: Prisma.BenchmarkCreateManyArgs<ExtArgs>
            result: BatchPayload
          }
          createManyAndReturn: {
            args: Prisma.BenchmarkCreateManyAndReturnArgs<ExtArgs>
            result: $Utils.PayloadToResult<Prisma.$BenchmarkPayload>[]
          }
          delete: {
            args: Prisma.BenchmarkDeleteArgs<ExtArgs>
            result: $Utils.PayloadToResult<Prisma.$BenchmarkPayload>
          }
          update: {
            args: Prisma.BenchmarkUpdateArgs<ExtArgs>
            result: $Utils.PayloadToResult<Prisma.$BenchmarkPayload>
          }
          deleteMany: {
            args: Prisma.BenchmarkDeleteManyArgs<ExtArgs>
            result: BatchPayload
          }
          updateMany: {
            args: Prisma.BenchmarkUpdateManyArgs<ExtArgs>
            result: BatchPayload
          }
          updateManyAndReturn: {
            args: Prisma.BenchmarkUpdateManyAndReturnArgs<ExtArgs>
            result: $Utils.PayloadToResult<Prisma.$BenchmarkPayload>[]
          }
          upsert: {
            args: Prisma.BenchmarkUpsertArgs<ExtArgs>
            result: $Utils.PayloadToResult<Prisma.$BenchmarkPayload>
          }
          aggregate: {
            args: Prisma.BenchmarkAggregateArgs<ExtArgs>
            result: $Utils.Optional<AggregateBenchmark>
          }
          groupBy: {
            args: Prisma.BenchmarkGroupByArgs<ExtArgs>
            result: $Utils.Optional<BenchmarkGroupByOutputType>[]
          }
          count: {
            args: Prisma.BenchmarkCountArgs<ExtArgs>
            result: $Utils.Optional<BenchmarkCountAggregateOutputType> | number
          }
        }
      }
    }
  } & {
    other: {
      payload: any
      operations: {
        $executeRaw: {
          args: [query: TemplateStringsArray | Prisma.Sql, ...values: any[]],
          result: any
        }
        $executeRawUnsafe: {
          args: [query: string, ...values: any[]],
          result: any
        }
        $queryRaw: {
          args: [query: TemplateStringsArray | Prisma.Sql, ...values: any[]],
          result: any
        }
        $queryRawUnsafe: {
          args: [query: string, ...values: any[]],
          result: any
        }
      }
    }
  }
  export const defineExtension: $Extensions.ExtendsHook<"define", Prisma.TypeMapCb, $Extensions.DefaultArgs>
  export type DefaultPrismaClient = PrismaClient
  export type ErrorFormat = 'pretty' | 'colorless' | 'minimal'
  export interface PrismaClientOptions {
    /**
     * Overwrites the datasource url from your schema.prisma file
     */
    datasources?: Datasources
    /**
     * Overwrites the datasource url from your schema.prisma file
     */
    datasourceUrl?: string
    /**
     * @default "colorless"
     */
    errorFormat?: ErrorFormat
    /**
     * @example
     * ```
     * // Shorthand for `emit: 'stdout'`
     * log: ['query', 'info', 'warn', 'error']
     * 
     * // Emit as events only
     * log: [
     *   { emit: 'event', level: 'query' },
     *   { emit: 'event', level: 'info' },
     *   { emit: 'event', level: 'warn' }
     *   { emit: 'event', level: 'error' }
     * ]
     * 
     * / Emit as events and log to stdout
     * og: [
     *  { emit: 'stdout', level: 'query' },
     *  { emit: 'stdout', level: 'info' },
     *  { emit: 'stdout', level: 'warn' }
     *  { emit: 'stdout', level: 'error' }
     * 
     * ```
     * Read more in our [docs](https://www.prisma.io/docs/reference/tools-and-interfaces/prisma-client/logging#the-log-option).
     */
    log?: (LogLevel | LogDefinition)[]
    /**
     * The default values for transactionOptions
     * maxWait ?= 2000
     * timeout ?= 5000
     */
    transactionOptions?: {
      maxWait?: number
      timeout?: number
      isolationLevel?: Prisma.TransactionIsolationLevel
    }
    /**
     * Instance of a Driver Adapter, e.g., like one provided by `@prisma/adapter-planetscale`
     */
    adapter?: runtime.SqlDriverAdapterFactory | null
    /**
     * Global configuration for omitting model fields by default.
     * 
     * @example
     * ```
     * const prisma = new PrismaClient({
     *   omit: {
     *     user: {
     *       password: true
     *     }
     *   }
     * })
     * ```
     */
    omit?: Prisma.GlobalOmitConfig
  }
  export type GlobalOmitConfig = {
    benchmark?: BenchmarkOmit
  }

  /* Types for Logging */
  export type LogLevel = 'info' | 'query' | 'warn' | 'error'
  export type LogDefinition = {
    level: LogLevel
    emit: 'stdout' | 'event'
  }

  export type CheckIsLogLevel<T> = T extends LogLevel ? T : never;

  export type GetLogType<T> = CheckIsLogLevel<
    T extends LogDefinition ? T['level'] : T
  >;

  export type GetEvents<T extends any[]> = T extends Array<LogLevel | LogDefinition>
    ? GetLogType<T[number]>
    : never;

  export type QueryEvent = {
    timestamp: Date
    query: string
    params: string
    duration: number
    target: string
  }

  export type LogEvent = {
    timestamp: Date
    message: string
    target: string
  }
  /* End Types for Logging */


  export type PrismaAction =
    | 'findUnique'
    | 'findUniqueOrThrow'
    | 'findMany'
    | 'findFirst'
    | 'findFirstOrThrow'
    | 'create'
    | 'createMany'
    | 'createManyAndReturn'
    | 'update'
    | 'updateMany'
    | 'updateManyAndReturn'
    | 'upsert'
    | 'delete'
    | 'deleteMany'
    | 'executeRaw'
    | 'queryRaw'
    | 'aggregate'
    | 'count'
    | 'runCommandRaw'
    | 'findRaw'
    | 'groupBy'

  // tested in getLogLevel.test.ts
  export function getLogLevel(log: Array<LogLevel | LogDefinition>): LogLevel | undefined;

  /**
   * `PrismaClient` proxy available in interactive transactions.
   */
  export type TransactionClient = Omit<Prisma.DefaultPrismaClient, runtime.ITXClientDenyList>

  export type Datasource = {
    url?: string
  }

  /**
   * Count Types
   */



  /**
   * Models
   */

  /**
   * Model Benchmark
   */

  export type AggregateBenchmark = {
    _count: BenchmarkCountAggregateOutputType | null
    _avg: BenchmarkAvgAggregateOutputType | null
    _sum: BenchmarkSumAggregateOutputType | null
    _min: BenchmarkMinAggregateOutputType | null
    _max: BenchmarkMaxAggregateOutputType | null
  }

  export type BenchmarkAvgAggregateOutputType = {
    ramGB: number | null
    fps: number | null
    vmaf: number | null
    fileSizeBytes: number | null
  }

  export type BenchmarkSumAggregateOutputType = {
    ramGB: number | null
    fps: number | null
    vmaf: number | null
    fileSizeBytes: number | null
  }

  export type BenchmarkMinAggregateOutputType = {
    id: string | null
    createdAt: Date | null
    cpuModel: string | null
    gpuModel: string | null
    ramGB: number | null
    os: string | null
    codec: string | null
    preset: string | null
    fps: number | null
    vmaf: number | null
    fileSizeBytes: number | null
    notes: string | null
  }

  export type BenchmarkMaxAggregateOutputType = {
    id: string | null
    createdAt: Date | null
    cpuModel: string | null
    gpuModel: string | null
    ramGB: number | null
    os: string | null
    codec: string | null
    preset: string | null
    fps: number | null
    vmaf: number | null
    fileSizeBytes: number | null
    notes: string | null
  }

  export type BenchmarkCountAggregateOutputType = {
    id: number
    createdAt: number
    cpuModel: number
    gpuModel: number
    ramGB: number
    os: number
    codec: number
    preset: number
    fps: number
    vmaf: number
    fileSizeBytes: number
    notes: number
    _all: number
  }


  export type BenchmarkAvgAggregateInputType = {
    ramGB?: true
    fps?: true
    vmaf?: true
    fileSizeBytes?: true
  }

  export type BenchmarkSumAggregateInputType = {
    ramGB?: true
    fps?: true
    vmaf?: true
    fileSizeBytes?: true
  }

  export type BenchmarkMinAggregateInputType = {
    id?: true
    createdAt?: true
    cpuModel?: true
    gpuModel?: true
    ramGB?: true
    os?: true
    codec?: true
    preset?: true
    fps?: true
    vmaf?: true
    fileSizeBytes?: true
    notes?: true
  }

  export type BenchmarkMaxAggregateInputType = {
    id?: true
    createdAt?: true
    cpuModel?: true
    gpuModel?: true
    ramGB?: true
    os?: true
    codec?: true
    preset?: true
    fps?: true
    vmaf?: true
    fileSizeBytes?: true
    notes?: true
  }

  export type BenchmarkCountAggregateInputType = {
    id?: true
    createdAt?: true
    cpuModel?: true
    gpuModel?: true
    ramGB?: true
    os?: true
    codec?: true
    preset?: true
    fps?: true
    vmaf?: true
    fileSizeBytes?: true
    notes?: true
    _all?: true
  }

  export type BenchmarkAggregateArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Filter which Benchmark to aggregate.
     */
    where?: BenchmarkWhereInput
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/sorting Sorting Docs}
     * 
     * Determine the order of Benchmarks to fetch.
     */
    orderBy?: BenchmarkOrderByWithRelationInput | BenchmarkOrderByWithRelationInput[]
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/pagination#cursor-based-pagination Cursor Docs}
     * 
     * Sets the start position
     */
    cursor?: BenchmarkWhereUniqueInput
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/pagination Pagination Docs}
     * 
     * Take `±n` Benchmarks from the position of the cursor.
     */
    take?: number
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/pagination Pagination Docs}
     * 
     * Skip the first `n` Benchmarks.
     */
    skip?: number
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/aggregations Aggregation Docs}
     * 
     * Count returned Benchmarks
    **/
    _count?: true | BenchmarkCountAggregateInputType
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/aggregations Aggregation Docs}
     * 
     * Select which fields to average
    **/
    _avg?: BenchmarkAvgAggregateInputType
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/aggregations Aggregation Docs}
     * 
     * Select which fields to sum
    **/
    _sum?: BenchmarkSumAggregateInputType
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/aggregations Aggregation Docs}
     * 
     * Select which fields to find the minimum value
    **/
    _min?: BenchmarkMinAggregateInputType
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/aggregations Aggregation Docs}
     * 
     * Select which fields to find the maximum value
    **/
    _max?: BenchmarkMaxAggregateInputType
  }

  export type GetBenchmarkAggregateType<T extends BenchmarkAggregateArgs> = {
        [P in keyof T & keyof AggregateBenchmark]: P extends '_count' | 'count'
      ? T[P] extends true
        ? number
        : GetScalarType<T[P], AggregateBenchmark[P]>
      : GetScalarType<T[P], AggregateBenchmark[P]>
  }




  export type BenchmarkGroupByArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    where?: BenchmarkWhereInput
    orderBy?: BenchmarkOrderByWithAggregationInput | BenchmarkOrderByWithAggregationInput[]
    by: BenchmarkScalarFieldEnum[] | BenchmarkScalarFieldEnum
    having?: BenchmarkScalarWhereWithAggregatesInput
    take?: number
    skip?: number
    _count?: BenchmarkCountAggregateInputType | true
    _avg?: BenchmarkAvgAggregateInputType
    _sum?: BenchmarkSumAggregateInputType
    _min?: BenchmarkMinAggregateInputType
    _max?: BenchmarkMaxAggregateInputType
  }

  export type BenchmarkGroupByOutputType = {
    id: string
    createdAt: Date
    cpuModel: string
    gpuModel: string | null
    ramGB: number
    os: string
    codec: string
    preset: string
    fps: number
    vmaf: number | null
    fileSizeBytes: number
    notes: string | null
    _count: BenchmarkCountAggregateOutputType | null
    _avg: BenchmarkAvgAggregateOutputType | null
    _sum: BenchmarkSumAggregateOutputType | null
    _min: BenchmarkMinAggregateOutputType | null
    _max: BenchmarkMaxAggregateOutputType | null
  }

  type GetBenchmarkGroupByPayload<T extends BenchmarkGroupByArgs> = Prisma.PrismaPromise<
    Array<
      PickEnumerable<BenchmarkGroupByOutputType, T['by']> &
        {
          [P in ((keyof T) & (keyof BenchmarkGroupByOutputType))]: P extends '_count'
            ? T[P] extends boolean
              ? number
              : GetScalarType<T[P], BenchmarkGroupByOutputType[P]>
            : GetScalarType<T[P], BenchmarkGroupByOutputType[P]>
        }
      >
    >


  export type BenchmarkSelect<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = $Extensions.GetSelect<{
    id?: boolean
    createdAt?: boolean
    cpuModel?: boolean
    gpuModel?: boolean
    ramGB?: boolean
    os?: boolean
    codec?: boolean
    preset?: boolean
    fps?: boolean
    vmaf?: boolean
    fileSizeBytes?: boolean
    notes?: boolean
  }, ExtArgs["result"]["benchmark"]>

  export type BenchmarkSelectCreateManyAndReturn<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = $Extensions.GetSelect<{
    id?: boolean
    createdAt?: boolean
    cpuModel?: boolean
    gpuModel?: boolean
    ramGB?: boolean
    os?: boolean
    codec?: boolean
    preset?: boolean
    fps?: boolean
    vmaf?: boolean
    fileSizeBytes?: boolean
    notes?: boolean
  }, ExtArgs["result"]["benchmark"]>

  export type BenchmarkSelectUpdateManyAndReturn<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = $Extensions.GetSelect<{
    id?: boolean
    createdAt?: boolean
    cpuModel?: boolean
    gpuModel?: boolean
    ramGB?: boolean
    os?: boolean
    codec?: boolean
    preset?: boolean
    fps?: boolean
    vmaf?: boolean
    fileSizeBytes?: boolean
    notes?: boolean
  }, ExtArgs["result"]["benchmark"]>

  export type BenchmarkSelectScalar = {
    id?: boolean
    createdAt?: boolean
    cpuModel?: boolean
    gpuModel?: boolean
    ramGB?: boolean
    os?: boolean
    codec?: boolean
    preset?: boolean
    fps?: boolean
    vmaf?: boolean
    fileSizeBytes?: boolean
    notes?: boolean
  }

  export type BenchmarkOmit<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = $Extensions.GetOmit<"id" | "createdAt" | "cpuModel" | "gpuModel" | "ramGB" | "os" | "codec" | "preset" | "fps" | "vmaf" | "fileSizeBytes" | "notes", ExtArgs["result"]["benchmark"]>

  export type $BenchmarkPayload<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    name: "Benchmark"
    objects: {}
    scalars: $Extensions.GetPayloadResult<{
      id: string
      createdAt: Date
      cpuModel: string
      gpuModel: string | null
      ramGB: number
      os: string
      codec: string
      preset: string
      fps: number
      vmaf: number | null
      fileSizeBytes: number
      notes: string | null
    }, ExtArgs["result"]["benchmark"]>
    composites: {}
  }

  type BenchmarkGetPayload<S extends boolean | null | undefined | BenchmarkDefaultArgs> = $Result.GetResult<Prisma.$BenchmarkPayload, S>

  type BenchmarkCountArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> =
    Omit<BenchmarkFindManyArgs, 'select' | 'include' | 'distinct' | 'omit'> & {
      select?: BenchmarkCountAggregateInputType | true
    }

  export interface BenchmarkDelegate<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs, GlobalOmitOptions = {}> {
    [K: symbol]: { types: Prisma.TypeMap<ExtArgs>['model']['Benchmark'], meta: { name: 'Benchmark' } }
    /**
     * Find zero or one Benchmark that matches the filter.
     * @param {BenchmarkFindUniqueArgs} args - Arguments to find a Benchmark
     * @example
     * // Get one Benchmark
     * const benchmark = await prisma.benchmark.findUnique({
     *   where: {
     *     // ... provide filter here
     *   }
     * })
     */
    findUnique<T extends BenchmarkFindUniqueArgs>(args: SelectSubset<T, BenchmarkFindUniqueArgs<ExtArgs>>): Prisma__BenchmarkClient<$Result.GetResult<Prisma.$BenchmarkPayload<ExtArgs>, T, "findUnique", GlobalOmitOptions> | null, null, ExtArgs, GlobalOmitOptions>

    /**
     * Find one Benchmark that matches the filter or throw an error with `error.code='P2025'`
     * if no matches were found.
     * @param {BenchmarkFindUniqueOrThrowArgs} args - Arguments to find a Benchmark
     * @example
     * // Get one Benchmark
     * const benchmark = await prisma.benchmark.findUniqueOrThrow({
     *   where: {
     *     // ... provide filter here
     *   }
     * })
     */
    findUniqueOrThrow<T extends BenchmarkFindUniqueOrThrowArgs>(args: SelectSubset<T, BenchmarkFindUniqueOrThrowArgs<ExtArgs>>): Prisma__BenchmarkClient<$Result.GetResult<Prisma.$BenchmarkPayload<ExtArgs>, T, "findUniqueOrThrow", GlobalOmitOptions>, never, ExtArgs, GlobalOmitOptions>

    /**
     * Find the first Benchmark that matches the filter.
     * Note, that providing `undefined` is treated as the value not being there.
     * Read more here: https://pris.ly/d/null-undefined
     * @param {BenchmarkFindFirstArgs} args - Arguments to find a Benchmark
     * @example
     * // Get one Benchmark
     * const benchmark = await prisma.benchmark.findFirst({
     *   where: {
     *     // ... provide filter here
     *   }
     * })
     */
    findFirst<T extends BenchmarkFindFirstArgs>(args?: SelectSubset<T, BenchmarkFindFirstArgs<ExtArgs>>): Prisma__BenchmarkClient<$Result.GetResult<Prisma.$BenchmarkPayload<ExtArgs>, T, "findFirst", GlobalOmitOptions> | null, null, ExtArgs, GlobalOmitOptions>

    /**
     * Find the first Benchmark that matches the filter or
     * throw `PrismaKnownClientError` with `P2025` code if no matches were found.
     * Note, that providing `undefined` is treated as the value not being there.
     * Read more here: https://pris.ly/d/null-undefined
     * @param {BenchmarkFindFirstOrThrowArgs} args - Arguments to find a Benchmark
     * @example
     * // Get one Benchmark
     * const benchmark = await prisma.benchmark.findFirstOrThrow({
     *   where: {
     *     // ... provide filter here
     *   }
     * })
     */
    findFirstOrThrow<T extends BenchmarkFindFirstOrThrowArgs>(args?: SelectSubset<T, BenchmarkFindFirstOrThrowArgs<ExtArgs>>): Prisma__BenchmarkClient<$Result.GetResult<Prisma.$BenchmarkPayload<ExtArgs>, T, "findFirstOrThrow", GlobalOmitOptions>, never, ExtArgs, GlobalOmitOptions>

    /**
     * Find zero or more Benchmarks that matches the filter.
     * Note, that providing `undefined` is treated as the value not being there.
     * Read more here: https://pris.ly/d/null-undefined
     * @param {BenchmarkFindManyArgs} args - Arguments to filter and select certain fields only.
     * @example
     * // Get all Benchmarks
     * const benchmarks = await prisma.benchmark.findMany()
     * 
     * // Get first 10 Benchmarks
     * const benchmarks = await prisma.benchmark.findMany({ take: 10 })
     * 
     * // Only select the `id`
     * const benchmarkWithIdOnly = await prisma.benchmark.findMany({ select: { id: true } })
     * 
     */
    findMany<T extends BenchmarkFindManyArgs>(args?: SelectSubset<T, BenchmarkFindManyArgs<ExtArgs>>): Prisma.PrismaPromise<$Result.GetResult<Prisma.$BenchmarkPayload<ExtArgs>, T, "findMany", GlobalOmitOptions>>

    /**
     * Create a Benchmark.
     * @param {BenchmarkCreateArgs} args - Arguments to create a Benchmark.
     * @example
     * // Create one Benchmark
     * const Benchmark = await prisma.benchmark.create({
     *   data: {
     *     // ... data to create a Benchmark
     *   }
     * })
     * 
     */
    create<T extends BenchmarkCreateArgs>(args: SelectSubset<T, BenchmarkCreateArgs<ExtArgs>>): Prisma__BenchmarkClient<$Result.GetResult<Prisma.$BenchmarkPayload<ExtArgs>, T, "create", GlobalOmitOptions>, never, ExtArgs, GlobalOmitOptions>

    /**
     * Create many Benchmarks.
     * @param {BenchmarkCreateManyArgs} args - Arguments to create many Benchmarks.
     * @example
     * // Create many Benchmarks
     * const benchmark = await prisma.benchmark.createMany({
     *   data: [
     *     // ... provide data here
     *   ]
     * })
     *     
     */
    createMany<T extends BenchmarkCreateManyArgs>(args?: SelectSubset<T, BenchmarkCreateManyArgs<ExtArgs>>): Prisma.PrismaPromise<BatchPayload>

    /**
     * Create many Benchmarks and returns the data saved in the database.
     * @param {BenchmarkCreateManyAndReturnArgs} args - Arguments to create many Benchmarks.
     * @example
     * // Create many Benchmarks
     * const benchmark = await prisma.benchmark.createManyAndReturn({
     *   data: [
     *     // ... provide data here
     *   ]
     * })
     * 
     * // Create many Benchmarks and only return the `id`
     * const benchmarkWithIdOnly = await prisma.benchmark.createManyAndReturn({
     *   select: { id: true },
     *   data: [
     *     // ... provide data here
     *   ]
     * })
     * Note, that providing `undefined` is treated as the value not being there.
     * Read more here: https://pris.ly/d/null-undefined
     * 
     */
    createManyAndReturn<T extends BenchmarkCreateManyAndReturnArgs>(args?: SelectSubset<T, BenchmarkCreateManyAndReturnArgs<ExtArgs>>): Prisma.PrismaPromise<$Result.GetResult<Prisma.$BenchmarkPayload<ExtArgs>, T, "createManyAndReturn", GlobalOmitOptions>>

    /**
     * Delete a Benchmark.
     * @param {BenchmarkDeleteArgs} args - Arguments to delete one Benchmark.
     * @example
     * // Delete one Benchmark
     * const Benchmark = await prisma.benchmark.delete({
     *   where: {
     *     // ... filter to delete one Benchmark
     *   }
     * })
     * 
     */
    delete<T extends BenchmarkDeleteArgs>(args: SelectSubset<T, BenchmarkDeleteArgs<ExtArgs>>): Prisma__BenchmarkClient<$Result.GetResult<Prisma.$BenchmarkPayload<ExtArgs>, T, "delete", GlobalOmitOptions>, never, ExtArgs, GlobalOmitOptions>

    /**
     * Update one Benchmark.
     * @param {BenchmarkUpdateArgs} args - Arguments to update one Benchmark.
     * @example
     * // Update one Benchmark
     * const benchmark = await prisma.benchmark.update({
     *   where: {
     *     // ... provide filter here
     *   },
     *   data: {
     *     // ... provide data here
     *   }
     * })
     * 
     */
    update<T extends BenchmarkUpdateArgs>(args: SelectSubset<T, BenchmarkUpdateArgs<ExtArgs>>): Prisma__BenchmarkClient<$Result.GetResult<Prisma.$BenchmarkPayload<ExtArgs>, T, "update", GlobalOmitOptions>, never, ExtArgs, GlobalOmitOptions>

    /**
     * Delete zero or more Benchmarks.
     * @param {BenchmarkDeleteManyArgs} args - Arguments to filter Benchmarks to delete.
     * @example
     * // Delete a few Benchmarks
     * const { count } = await prisma.benchmark.deleteMany({
     *   where: {
     *     // ... provide filter here
     *   }
     * })
     * 
     */
    deleteMany<T extends BenchmarkDeleteManyArgs>(args?: SelectSubset<T, BenchmarkDeleteManyArgs<ExtArgs>>): Prisma.PrismaPromise<BatchPayload>

    /**
     * Update zero or more Benchmarks.
     * Note, that providing `undefined` is treated as the value not being there.
     * Read more here: https://pris.ly/d/null-undefined
     * @param {BenchmarkUpdateManyArgs} args - Arguments to update one or more rows.
     * @example
     * // Update many Benchmarks
     * const benchmark = await prisma.benchmark.updateMany({
     *   where: {
     *     // ... provide filter here
     *   },
     *   data: {
     *     // ... provide data here
     *   }
     * })
     * 
     */
    updateMany<T extends BenchmarkUpdateManyArgs>(args: SelectSubset<T, BenchmarkUpdateManyArgs<ExtArgs>>): Prisma.PrismaPromise<BatchPayload>

    /**
     * Update zero or more Benchmarks and returns the data updated in the database.
     * @param {BenchmarkUpdateManyAndReturnArgs} args - Arguments to update many Benchmarks.
     * @example
     * // Update many Benchmarks
     * const benchmark = await prisma.benchmark.updateManyAndReturn({
     *   where: {
     *     // ... provide filter here
     *   },
     *   data: [
     *     // ... provide data here
     *   ]
     * })
     * 
     * // Update zero or more Benchmarks and only return the `id`
     * const benchmarkWithIdOnly = await prisma.benchmark.updateManyAndReturn({
     *   select: { id: true },
     *   where: {
     *     // ... provide filter here
     *   },
     *   data: [
     *     // ... provide data here
     *   ]
     * })
     * Note, that providing `undefined` is treated as the value not being there.
     * Read more here: https://pris.ly/d/null-undefined
     * 
     */
    updateManyAndReturn<T extends BenchmarkUpdateManyAndReturnArgs>(args: SelectSubset<T, BenchmarkUpdateManyAndReturnArgs<ExtArgs>>): Prisma.PrismaPromise<$Result.GetResult<Prisma.$BenchmarkPayload<ExtArgs>, T, "updateManyAndReturn", GlobalOmitOptions>>

    /**
     * Create or update one Benchmark.
     * @param {BenchmarkUpsertArgs} args - Arguments to update or create a Benchmark.
     * @example
     * // Update or create a Benchmark
     * const benchmark = await prisma.benchmark.upsert({
     *   create: {
     *     // ... data to create a Benchmark
     *   },
     *   update: {
     *     // ... in case it already exists, update
     *   },
     *   where: {
     *     // ... the filter for the Benchmark we want to update
     *   }
     * })
     */
    upsert<T extends BenchmarkUpsertArgs>(args: SelectSubset<T, BenchmarkUpsertArgs<ExtArgs>>): Prisma__BenchmarkClient<$Result.GetResult<Prisma.$BenchmarkPayload<ExtArgs>, T, "upsert", GlobalOmitOptions>, never, ExtArgs, GlobalOmitOptions>


    /**
     * Count the number of Benchmarks.
     * Note, that providing `undefined` is treated as the value not being there.
     * Read more here: https://pris.ly/d/null-undefined
     * @param {BenchmarkCountArgs} args - Arguments to filter Benchmarks to count.
     * @example
     * // Count the number of Benchmarks
     * const count = await prisma.benchmark.count({
     *   where: {
     *     // ... the filter for the Benchmarks we want to count
     *   }
     * })
    **/
    count<T extends BenchmarkCountArgs>(
      args?: Subset<T, BenchmarkCountArgs>,
    ): Prisma.PrismaPromise<
      T extends $Utils.Record<'select', any>
        ? T['select'] extends true
          ? number
          : GetScalarType<T['select'], BenchmarkCountAggregateOutputType>
        : number
    >

    /**
     * Allows you to perform aggregations operations on a Benchmark.
     * Note, that providing `undefined` is treated as the value not being there.
     * Read more here: https://pris.ly/d/null-undefined
     * @param {BenchmarkAggregateArgs} args - Select which aggregations you would like to apply and on what fields.
     * @example
     * // Ordered by age ascending
     * // Where email contains prisma.io
     * // Limited to the 10 users
     * const aggregations = await prisma.user.aggregate({
     *   _avg: {
     *     age: true,
     *   },
     *   where: {
     *     email: {
     *       contains: "prisma.io",
     *     },
     *   },
     *   orderBy: {
     *     age: "asc",
     *   },
     *   take: 10,
     * })
    **/
    aggregate<T extends BenchmarkAggregateArgs>(args: Subset<T, BenchmarkAggregateArgs>): Prisma.PrismaPromise<GetBenchmarkAggregateType<T>>

    /**
     * Group by Benchmark.
     * Note, that providing `undefined` is treated as the value not being there.
     * Read more here: https://pris.ly/d/null-undefined
     * @param {BenchmarkGroupByArgs} args - Group by arguments.
     * @example
     * // Group by city, order by createdAt, get count
     * const result = await prisma.user.groupBy({
     *   by: ['city', 'createdAt'],
     *   orderBy: {
     *     createdAt: true
     *   },
     *   _count: {
     *     _all: true
     *   },
     * })
     * 
    **/
    groupBy<
      T extends BenchmarkGroupByArgs,
      HasSelectOrTake extends Or<
        Extends<'skip', Keys<T>>,
        Extends<'take', Keys<T>>
      >,
      OrderByArg extends True extends HasSelectOrTake
        ? { orderBy: BenchmarkGroupByArgs['orderBy'] }
        : { orderBy?: BenchmarkGroupByArgs['orderBy'] },
      OrderFields extends ExcludeUnderscoreKeys<Keys<MaybeTupleToUnion<T['orderBy']>>>,
      ByFields extends MaybeTupleToUnion<T['by']>,
      ByValid extends Has<ByFields, OrderFields>,
      HavingFields extends GetHavingFields<T['having']>,
      HavingValid extends Has<ByFields, HavingFields>,
      ByEmpty extends T['by'] extends never[] ? True : False,
      InputErrors extends ByEmpty extends True
      ? `Error: "by" must not be empty.`
      : HavingValid extends False
      ? {
          [P in HavingFields]: P extends ByFields
            ? never
            : P extends string
            ? `Error: Field "${P}" used in "having" needs to be provided in "by".`
            : [
                Error,
                'Field ',
                P,
                ` in "having" needs to be provided in "by"`,
              ]
        }[HavingFields]
      : 'take' extends Keys<T>
      ? 'orderBy' extends Keys<T>
        ? ByValid extends True
          ? {}
          : {
              [P in OrderFields]: P extends ByFields
                ? never
                : `Error: Field "${P}" in "orderBy" needs to be provided in "by"`
            }[OrderFields]
        : 'Error: If you provide "take", you also need to provide "orderBy"'
      : 'skip' extends Keys<T>
      ? 'orderBy' extends Keys<T>
        ? ByValid extends True
          ? {}
          : {
              [P in OrderFields]: P extends ByFields
                ? never
                : `Error: Field "${P}" in "orderBy" needs to be provided in "by"`
            }[OrderFields]
        : 'Error: If you provide "skip", you also need to provide "orderBy"'
      : ByValid extends True
      ? {}
      : {
          [P in OrderFields]: P extends ByFields
            ? never
            : `Error: Field "${P}" in "orderBy" needs to be provided in "by"`
        }[OrderFields]
    >(args: SubsetIntersection<T, BenchmarkGroupByArgs, OrderByArg> & InputErrors): {} extends InputErrors ? GetBenchmarkGroupByPayload<T> : Prisma.PrismaPromise<InputErrors>
  /**
   * Fields of the Benchmark model
   */
  readonly fields: BenchmarkFieldRefs;
  }

  /**
   * The delegate class that acts as a "Promise-like" for Benchmark.
   * Why is this prefixed with `Prisma__`?
   * Because we want to prevent naming conflicts as mentioned in
   * https://github.com/prisma/prisma-client-js/issues/707
   */
  export interface Prisma__BenchmarkClient<T, Null = never, ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs, GlobalOmitOptions = {}> extends Prisma.PrismaPromise<T> {
    readonly [Symbol.toStringTag]: "PrismaPromise"
    /**
     * Attaches callbacks for the resolution and/or rejection of the Promise.
     * @param onfulfilled The callback to execute when the Promise is resolved.
     * @param onrejected The callback to execute when the Promise is rejected.
     * @returns A Promise for the completion of which ever callback is executed.
     */
    then<TResult1 = T, TResult2 = never>(onfulfilled?: ((value: T) => TResult1 | PromiseLike<TResult1>) | undefined | null, onrejected?: ((reason: any) => TResult2 | PromiseLike<TResult2>) | undefined | null): $Utils.JsPromise<TResult1 | TResult2>
    /**
     * Attaches a callback for only the rejection of the Promise.
     * @param onrejected The callback to execute when the Promise is rejected.
     * @returns A Promise for the completion of the callback.
     */
    catch<TResult = never>(onrejected?: ((reason: any) => TResult | PromiseLike<TResult>) | undefined | null): $Utils.JsPromise<T | TResult>
    /**
     * Attaches a callback that is invoked when the Promise is settled (fulfilled or rejected). The
     * resolved value cannot be modified from the callback.
     * @param onfinally The callback to execute when the Promise is settled (fulfilled or rejected).
     * @returns A Promise for the completion of the callback.
     */
    finally(onfinally?: (() => void) | undefined | null): $Utils.JsPromise<T>
  }




  /**
   * Fields of the Benchmark model
   */
  interface BenchmarkFieldRefs {
    readonly id: FieldRef<"Benchmark", 'String'>
    readonly createdAt: FieldRef<"Benchmark", 'DateTime'>
    readonly cpuModel: FieldRef<"Benchmark", 'String'>
    readonly gpuModel: FieldRef<"Benchmark", 'String'>
    readonly ramGB: FieldRef<"Benchmark", 'Int'>
    readonly os: FieldRef<"Benchmark", 'String'>
    readonly codec: FieldRef<"Benchmark", 'String'>
    readonly preset: FieldRef<"Benchmark", 'String'>
    readonly fps: FieldRef<"Benchmark", 'Float'>
    readonly vmaf: FieldRef<"Benchmark", 'Float'>
    readonly fileSizeBytes: FieldRef<"Benchmark", 'Int'>
    readonly notes: FieldRef<"Benchmark", 'String'>
  }
    

  // Custom InputTypes
  /**
   * Benchmark findUnique
   */
  export type BenchmarkFindUniqueArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Select specific fields to fetch from the Benchmark
     */
    select?: BenchmarkSelect<ExtArgs> | null
    /**
     * Omit specific fields from the Benchmark
     */
    omit?: BenchmarkOmit<ExtArgs> | null
    /**
     * Filter, which Benchmark to fetch.
     */
    where: BenchmarkWhereUniqueInput
  }

  /**
   * Benchmark findUniqueOrThrow
   */
  export type BenchmarkFindUniqueOrThrowArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Select specific fields to fetch from the Benchmark
     */
    select?: BenchmarkSelect<ExtArgs> | null
    /**
     * Omit specific fields from the Benchmark
     */
    omit?: BenchmarkOmit<ExtArgs> | null
    /**
     * Filter, which Benchmark to fetch.
     */
    where: BenchmarkWhereUniqueInput
  }

  /**
   * Benchmark findFirst
   */
  export type BenchmarkFindFirstArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Select specific fields to fetch from the Benchmark
     */
    select?: BenchmarkSelect<ExtArgs> | null
    /**
     * Omit specific fields from the Benchmark
     */
    omit?: BenchmarkOmit<ExtArgs> | null
    /**
     * Filter, which Benchmark to fetch.
     */
    where?: BenchmarkWhereInput
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/sorting Sorting Docs}
     * 
     * Determine the order of Benchmarks to fetch.
     */
    orderBy?: BenchmarkOrderByWithRelationInput | BenchmarkOrderByWithRelationInput[]
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/pagination#cursor-based-pagination Cursor Docs}
     * 
     * Sets the position for searching for Benchmarks.
     */
    cursor?: BenchmarkWhereUniqueInput
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/pagination Pagination Docs}
     * 
     * Take `±n` Benchmarks from the position of the cursor.
     */
    take?: number
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/pagination Pagination Docs}
     * 
     * Skip the first `n` Benchmarks.
     */
    skip?: number
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/distinct Distinct Docs}
     * 
     * Filter by unique combinations of Benchmarks.
     */
    distinct?: BenchmarkScalarFieldEnum | BenchmarkScalarFieldEnum[]
  }

  /**
   * Benchmark findFirstOrThrow
   */
  export type BenchmarkFindFirstOrThrowArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Select specific fields to fetch from the Benchmark
     */
    select?: BenchmarkSelect<ExtArgs> | null
    /**
     * Omit specific fields from the Benchmark
     */
    omit?: BenchmarkOmit<ExtArgs> | null
    /**
     * Filter, which Benchmark to fetch.
     */
    where?: BenchmarkWhereInput
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/sorting Sorting Docs}
     * 
     * Determine the order of Benchmarks to fetch.
     */
    orderBy?: BenchmarkOrderByWithRelationInput | BenchmarkOrderByWithRelationInput[]
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/pagination#cursor-based-pagination Cursor Docs}
     * 
     * Sets the position for searching for Benchmarks.
     */
    cursor?: BenchmarkWhereUniqueInput
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/pagination Pagination Docs}
     * 
     * Take `±n` Benchmarks from the position of the cursor.
     */
    take?: number
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/pagination Pagination Docs}
     * 
     * Skip the first `n` Benchmarks.
     */
    skip?: number
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/distinct Distinct Docs}
     * 
     * Filter by unique combinations of Benchmarks.
     */
    distinct?: BenchmarkScalarFieldEnum | BenchmarkScalarFieldEnum[]
  }

  /**
   * Benchmark findMany
   */
  export type BenchmarkFindManyArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Select specific fields to fetch from the Benchmark
     */
    select?: BenchmarkSelect<ExtArgs> | null
    /**
     * Omit specific fields from the Benchmark
     */
    omit?: BenchmarkOmit<ExtArgs> | null
    /**
     * Filter, which Benchmarks to fetch.
     */
    where?: BenchmarkWhereInput
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/sorting Sorting Docs}
     * 
     * Determine the order of Benchmarks to fetch.
     */
    orderBy?: BenchmarkOrderByWithRelationInput | BenchmarkOrderByWithRelationInput[]
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/pagination#cursor-based-pagination Cursor Docs}
     * 
     * Sets the position for listing Benchmarks.
     */
    cursor?: BenchmarkWhereUniqueInput
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/pagination Pagination Docs}
     * 
     * Take `±n` Benchmarks from the position of the cursor.
     */
    take?: number
    /**
     * {@link https://www.prisma.io/docs/concepts/components/prisma-client/pagination Pagination Docs}
     * 
     * Skip the first `n` Benchmarks.
     */
    skip?: number
    distinct?: BenchmarkScalarFieldEnum | BenchmarkScalarFieldEnum[]
  }

  /**
   * Benchmark create
   */
  export type BenchmarkCreateArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Select specific fields to fetch from the Benchmark
     */
    select?: BenchmarkSelect<ExtArgs> | null
    /**
     * Omit specific fields from the Benchmark
     */
    omit?: BenchmarkOmit<ExtArgs> | null
    /**
     * The data needed to create a Benchmark.
     */
    data: XOR<BenchmarkCreateInput, BenchmarkUncheckedCreateInput>
  }

  /**
   * Benchmark createMany
   */
  export type BenchmarkCreateManyArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * The data used to create many Benchmarks.
     */
    data: BenchmarkCreateManyInput | BenchmarkCreateManyInput[]
    skipDuplicates?: boolean
  }

  /**
   * Benchmark createManyAndReturn
   */
  export type BenchmarkCreateManyAndReturnArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Select specific fields to fetch from the Benchmark
     */
    select?: BenchmarkSelectCreateManyAndReturn<ExtArgs> | null
    /**
     * Omit specific fields from the Benchmark
     */
    omit?: BenchmarkOmit<ExtArgs> | null
    /**
     * The data used to create many Benchmarks.
     */
    data: BenchmarkCreateManyInput | BenchmarkCreateManyInput[]
    skipDuplicates?: boolean
  }

  /**
   * Benchmark update
   */
  export type BenchmarkUpdateArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Select specific fields to fetch from the Benchmark
     */
    select?: BenchmarkSelect<ExtArgs> | null
    /**
     * Omit specific fields from the Benchmark
     */
    omit?: BenchmarkOmit<ExtArgs> | null
    /**
     * The data needed to update a Benchmark.
     */
    data: XOR<BenchmarkUpdateInput, BenchmarkUncheckedUpdateInput>
    /**
     * Choose, which Benchmark to update.
     */
    where: BenchmarkWhereUniqueInput
  }

  /**
   * Benchmark updateMany
   */
  export type BenchmarkUpdateManyArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * The data used to update Benchmarks.
     */
    data: XOR<BenchmarkUpdateManyMutationInput, BenchmarkUncheckedUpdateManyInput>
    /**
     * Filter which Benchmarks to update
     */
    where?: BenchmarkWhereInput
    /**
     * Limit how many Benchmarks to update.
     */
    limit?: number
  }

  /**
   * Benchmark updateManyAndReturn
   */
  export type BenchmarkUpdateManyAndReturnArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Select specific fields to fetch from the Benchmark
     */
    select?: BenchmarkSelectUpdateManyAndReturn<ExtArgs> | null
    /**
     * Omit specific fields from the Benchmark
     */
    omit?: BenchmarkOmit<ExtArgs> | null
    /**
     * The data used to update Benchmarks.
     */
    data: XOR<BenchmarkUpdateManyMutationInput, BenchmarkUncheckedUpdateManyInput>
    /**
     * Filter which Benchmarks to update
     */
    where?: BenchmarkWhereInput
    /**
     * Limit how many Benchmarks to update.
     */
    limit?: number
  }

  /**
   * Benchmark upsert
   */
  export type BenchmarkUpsertArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Select specific fields to fetch from the Benchmark
     */
    select?: BenchmarkSelect<ExtArgs> | null
    /**
     * Omit specific fields from the Benchmark
     */
    omit?: BenchmarkOmit<ExtArgs> | null
    /**
     * The filter to search for the Benchmark to update in case it exists.
     */
    where: BenchmarkWhereUniqueInput
    /**
     * In case the Benchmark found by the `where` argument doesn't exist, create a new Benchmark with this data.
     */
    create: XOR<BenchmarkCreateInput, BenchmarkUncheckedCreateInput>
    /**
     * In case the Benchmark was found with the provided `where` argument, update it with this data.
     */
    update: XOR<BenchmarkUpdateInput, BenchmarkUncheckedUpdateInput>
  }

  /**
   * Benchmark delete
   */
  export type BenchmarkDeleteArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Select specific fields to fetch from the Benchmark
     */
    select?: BenchmarkSelect<ExtArgs> | null
    /**
     * Omit specific fields from the Benchmark
     */
    omit?: BenchmarkOmit<ExtArgs> | null
    /**
     * Filter which Benchmark to delete.
     */
    where: BenchmarkWhereUniqueInput
  }

  /**
   * Benchmark deleteMany
   */
  export type BenchmarkDeleteManyArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Filter which Benchmarks to delete
     */
    where?: BenchmarkWhereInput
    /**
     * Limit how many Benchmarks to delete.
     */
    limit?: number
  }

  /**
   * Benchmark without action
   */
  export type BenchmarkDefaultArgs<ExtArgs extends $Extensions.InternalArgs = $Extensions.DefaultArgs> = {
    /**
     * Select specific fields to fetch from the Benchmark
     */
    select?: BenchmarkSelect<ExtArgs> | null
    /**
     * Omit specific fields from the Benchmark
     */
    omit?: BenchmarkOmit<ExtArgs> | null
  }


  /**
   * Enums
   */

  export const TransactionIsolationLevel: {
    ReadUncommitted: 'ReadUncommitted',
    ReadCommitted: 'ReadCommitted',
    RepeatableRead: 'RepeatableRead',
    Serializable: 'Serializable'
  };

  export type TransactionIsolationLevel = (typeof TransactionIsolationLevel)[keyof typeof TransactionIsolationLevel]


  export const BenchmarkScalarFieldEnum: {
    id: 'id',
    createdAt: 'createdAt',
    cpuModel: 'cpuModel',
    gpuModel: 'gpuModel',
    ramGB: 'ramGB',
    os: 'os',
    codec: 'codec',
    preset: 'preset',
    fps: 'fps',
    vmaf: 'vmaf',
    fileSizeBytes: 'fileSizeBytes',
    notes: 'notes'
  };

  export type BenchmarkScalarFieldEnum = (typeof BenchmarkScalarFieldEnum)[keyof typeof BenchmarkScalarFieldEnum]


  export const SortOrder: {
    asc: 'asc',
    desc: 'desc'
  };

  export type SortOrder = (typeof SortOrder)[keyof typeof SortOrder]


  export const QueryMode: {
    default: 'default',
    insensitive: 'insensitive'
  };

  export type QueryMode = (typeof QueryMode)[keyof typeof QueryMode]


  export const NullsOrder: {
    first: 'first',
    last: 'last'
  };

  export type NullsOrder = (typeof NullsOrder)[keyof typeof NullsOrder]


  /**
   * Field references
   */


  /**
   * Reference to a field of type 'String'
   */
  export type StringFieldRefInput<$PrismaModel> = FieldRefInputType<$PrismaModel, 'String'>
    


  /**
   * Reference to a field of type 'String[]'
   */
  export type ListStringFieldRefInput<$PrismaModel> = FieldRefInputType<$PrismaModel, 'String[]'>
    


  /**
   * Reference to a field of type 'DateTime'
   */
  export type DateTimeFieldRefInput<$PrismaModel> = FieldRefInputType<$PrismaModel, 'DateTime'>
    


  /**
   * Reference to a field of type 'DateTime[]'
   */
  export type ListDateTimeFieldRefInput<$PrismaModel> = FieldRefInputType<$PrismaModel, 'DateTime[]'>
    


  /**
   * Reference to a field of type 'Int'
   */
  export type IntFieldRefInput<$PrismaModel> = FieldRefInputType<$PrismaModel, 'Int'>
    


  /**
   * Reference to a field of type 'Int[]'
   */
  export type ListIntFieldRefInput<$PrismaModel> = FieldRefInputType<$PrismaModel, 'Int[]'>
    


  /**
   * Reference to a field of type 'Float'
   */
  export type FloatFieldRefInput<$PrismaModel> = FieldRefInputType<$PrismaModel, 'Float'>
    


  /**
   * Reference to a field of type 'Float[]'
   */
  export type ListFloatFieldRefInput<$PrismaModel> = FieldRefInputType<$PrismaModel, 'Float[]'>
    
  /**
   * Deep Input Types
   */


  export type BenchmarkWhereInput = {
    AND?: BenchmarkWhereInput | BenchmarkWhereInput[]
    OR?: BenchmarkWhereInput[]
    NOT?: BenchmarkWhereInput | BenchmarkWhereInput[]
    id?: StringFilter<"Benchmark"> | string
    createdAt?: DateTimeFilter<"Benchmark"> | Date | string
    cpuModel?: StringFilter<"Benchmark"> | string
    gpuModel?: StringNullableFilter<"Benchmark"> | string | null
    ramGB?: IntFilter<"Benchmark"> | number
    os?: StringFilter<"Benchmark"> | string
    codec?: StringFilter<"Benchmark"> | string
    preset?: StringFilter<"Benchmark"> | string
    fps?: FloatFilter<"Benchmark"> | number
    vmaf?: FloatNullableFilter<"Benchmark"> | number | null
    fileSizeBytes?: IntFilter<"Benchmark"> | number
    notes?: StringNullableFilter<"Benchmark"> | string | null
  }

  export type BenchmarkOrderByWithRelationInput = {
    id?: SortOrder
    createdAt?: SortOrder
    cpuModel?: SortOrder
    gpuModel?: SortOrderInput | SortOrder
    ramGB?: SortOrder
    os?: SortOrder
    codec?: SortOrder
    preset?: SortOrder
    fps?: SortOrder
    vmaf?: SortOrderInput | SortOrder
    fileSizeBytes?: SortOrder
    notes?: SortOrderInput | SortOrder
  }

  export type BenchmarkWhereUniqueInput = Prisma.AtLeast<{
    id?: string
    AND?: BenchmarkWhereInput | BenchmarkWhereInput[]
    OR?: BenchmarkWhereInput[]
    NOT?: BenchmarkWhereInput | BenchmarkWhereInput[]
    createdAt?: DateTimeFilter<"Benchmark"> | Date | string
    cpuModel?: StringFilter<"Benchmark"> | string
    gpuModel?: StringNullableFilter<"Benchmark"> | string | null
    ramGB?: IntFilter<"Benchmark"> | number
    os?: StringFilter<"Benchmark"> | string
    codec?: StringFilter<"Benchmark"> | string
    preset?: StringFilter<"Benchmark"> | string
    fps?: FloatFilter<"Benchmark"> | number
    vmaf?: FloatNullableFilter<"Benchmark"> | number | null
    fileSizeBytes?: IntFilter<"Benchmark"> | number
    notes?: StringNullableFilter<"Benchmark"> | string | null
  }, "id">

  export type BenchmarkOrderByWithAggregationInput = {
    id?: SortOrder
    createdAt?: SortOrder
    cpuModel?: SortOrder
    gpuModel?: SortOrderInput | SortOrder
    ramGB?: SortOrder
    os?: SortOrder
    codec?: SortOrder
    preset?: SortOrder
    fps?: SortOrder
    vmaf?: SortOrderInput | SortOrder
    fileSizeBytes?: SortOrder
    notes?: SortOrderInput | SortOrder
    _count?: BenchmarkCountOrderByAggregateInput
    _avg?: BenchmarkAvgOrderByAggregateInput
    _max?: BenchmarkMaxOrderByAggregateInput
    _min?: BenchmarkMinOrderByAggregateInput
    _sum?: BenchmarkSumOrderByAggregateInput
  }

  export type BenchmarkScalarWhereWithAggregatesInput = {
    AND?: BenchmarkScalarWhereWithAggregatesInput | BenchmarkScalarWhereWithAggregatesInput[]
    OR?: BenchmarkScalarWhereWithAggregatesInput[]
    NOT?: BenchmarkScalarWhereWithAggregatesInput | BenchmarkScalarWhereWithAggregatesInput[]
    id?: StringWithAggregatesFilter<"Benchmark"> | string
    createdAt?: DateTimeWithAggregatesFilter<"Benchmark"> | Date | string
    cpuModel?: StringWithAggregatesFilter<"Benchmark"> | string
    gpuModel?: StringNullableWithAggregatesFilter<"Benchmark"> | string | null
    ramGB?: IntWithAggregatesFilter<"Benchmark"> | number
    os?: StringWithAggregatesFilter<"Benchmark"> | string
    codec?: StringWithAggregatesFilter<"Benchmark"> | string
    preset?: StringWithAggregatesFilter<"Benchmark"> | string
    fps?: FloatWithAggregatesFilter<"Benchmark"> | number
    vmaf?: FloatNullableWithAggregatesFilter<"Benchmark"> | number | null
    fileSizeBytes?: IntWithAggregatesFilter<"Benchmark"> | number
    notes?: StringNullableWithAggregatesFilter<"Benchmark"> | string | null
  }

  export type BenchmarkCreateInput = {
    id?: string
    createdAt?: Date | string
    cpuModel: string
    gpuModel?: string | null
    ramGB: number
    os: string
    codec: string
    preset: string
    fps: number
    vmaf?: number | null
    fileSizeBytes: number
    notes?: string | null
  }

  export type BenchmarkUncheckedCreateInput = {
    id?: string
    createdAt?: Date | string
    cpuModel: string
    gpuModel?: string | null
    ramGB: number
    os: string
    codec: string
    preset: string
    fps: number
    vmaf?: number | null
    fileSizeBytes: number
    notes?: string | null
  }

  export type BenchmarkUpdateInput = {
    id?: StringFieldUpdateOperationsInput | string
    createdAt?: DateTimeFieldUpdateOperationsInput | Date | string
    cpuModel?: StringFieldUpdateOperationsInput | string
    gpuModel?: NullableStringFieldUpdateOperationsInput | string | null
    ramGB?: IntFieldUpdateOperationsInput | number
    os?: StringFieldUpdateOperationsInput | string
    codec?: StringFieldUpdateOperationsInput | string
    preset?: StringFieldUpdateOperationsInput | string
    fps?: FloatFieldUpdateOperationsInput | number
    vmaf?: NullableFloatFieldUpdateOperationsInput | number | null
    fileSizeBytes?: IntFieldUpdateOperationsInput | number
    notes?: NullableStringFieldUpdateOperationsInput | string | null
  }

  export type BenchmarkUncheckedUpdateInput = {
    id?: StringFieldUpdateOperationsInput | string
    createdAt?: DateTimeFieldUpdateOperationsInput | Date | string
    cpuModel?: StringFieldUpdateOperationsInput | string
    gpuModel?: NullableStringFieldUpdateOperationsInput | string | null
    ramGB?: IntFieldUpdateOperationsInput | number
    os?: StringFieldUpdateOperationsInput | string
    codec?: StringFieldUpdateOperationsInput | string
    preset?: StringFieldUpdateOperationsInput | string
    fps?: FloatFieldUpdateOperationsInput | number
    vmaf?: NullableFloatFieldUpdateOperationsInput | number | null
    fileSizeBytes?: IntFieldUpdateOperationsInput | number
    notes?: NullableStringFieldUpdateOperationsInput | string | null
  }

  export type BenchmarkCreateManyInput = {
    id?: string
    createdAt?: Date | string
    cpuModel: string
    gpuModel?: string | null
    ramGB: number
    os: string
    codec: string
    preset: string
    fps: number
    vmaf?: number | null
    fileSizeBytes: number
    notes?: string | null
  }

  export type BenchmarkUpdateManyMutationInput = {
    id?: StringFieldUpdateOperationsInput | string
    createdAt?: DateTimeFieldUpdateOperationsInput | Date | string
    cpuModel?: StringFieldUpdateOperationsInput | string
    gpuModel?: NullableStringFieldUpdateOperationsInput | string | null
    ramGB?: IntFieldUpdateOperationsInput | number
    os?: StringFieldUpdateOperationsInput | string
    codec?: StringFieldUpdateOperationsInput | string
    preset?: StringFieldUpdateOperationsInput | string
    fps?: FloatFieldUpdateOperationsInput | number
    vmaf?: NullableFloatFieldUpdateOperationsInput | number | null
    fileSizeBytes?: IntFieldUpdateOperationsInput | number
    notes?: NullableStringFieldUpdateOperationsInput | string | null
  }

  export type BenchmarkUncheckedUpdateManyInput = {
    id?: StringFieldUpdateOperationsInput | string
    createdAt?: DateTimeFieldUpdateOperationsInput | Date | string
    cpuModel?: StringFieldUpdateOperationsInput | string
    gpuModel?: NullableStringFieldUpdateOperationsInput | string | null
    ramGB?: IntFieldUpdateOperationsInput | number
    os?: StringFieldUpdateOperationsInput | string
    codec?: StringFieldUpdateOperationsInput | string
    preset?: StringFieldUpdateOperationsInput | string
    fps?: FloatFieldUpdateOperationsInput | number
    vmaf?: NullableFloatFieldUpdateOperationsInput | number | null
    fileSizeBytes?: IntFieldUpdateOperationsInput | number
    notes?: NullableStringFieldUpdateOperationsInput | string | null
  }

  export type StringFilter<$PrismaModel = never> = {
    equals?: string | StringFieldRefInput<$PrismaModel>
    in?: string[] | ListStringFieldRefInput<$PrismaModel>
    notIn?: string[] | ListStringFieldRefInput<$PrismaModel>
    lt?: string | StringFieldRefInput<$PrismaModel>
    lte?: string | StringFieldRefInput<$PrismaModel>
    gt?: string | StringFieldRefInput<$PrismaModel>
    gte?: string | StringFieldRefInput<$PrismaModel>
    contains?: string | StringFieldRefInput<$PrismaModel>
    startsWith?: string | StringFieldRefInput<$PrismaModel>
    endsWith?: string | StringFieldRefInput<$PrismaModel>
    mode?: QueryMode
    not?: NestedStringFilter<$PrismaModel> | string
  }

  export type DateTimeFilter<$PrismaModel = never> = {
    equals?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    in?: Date[] | string[] | ListDateTimeFieldRefInput<$PrismaModel>
    notIn?: Date[] | string[] | ListDateTimeFieldRefInput<$PrismaModel>
    lt?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    lte?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    gt?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    gte?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    not?: NestedDateTimeFilter<$PrismaModel> | Date | string
  }

  export type StringNullableFilter<$PrismaModel = never> = {
    equals?: string | StringFieldRefInput<$PrismaModel> | null
    in?: string[] | ListStringFieldRefInput<$PrismaModel> | null
    notIn?: string[] | ListStringFieldRefInput<$PrismaModel> | null
    lt?: string | StringFieldRefInput<$PrismaModel>
    lte?: string | StringFieldRefInput<$PrismaModel>
    gt?: string | StringFieldRefInput<$PrismaModel>
    gte?: string | StringFieldRefInput<$PrismaModel>
    contains?: string | StringFieldRefInput<$PrismaModel>
    startsWith?: string | StringFieldRefInput<$PrismaModel>
    endsWith?: string | StringFieldRefInput<$PrismaModel>
    mode?: QueryMode
    not?: NestedStringNullableFilter<$PrismaModel> | string | null
  }

  export type IntFilter<$PrismaModel = never> = {
    equals?: number | IntFieldRefInput<$PrismaModel>
    in?: number[] | ListIntFieldRefInput<$PrismaModel>
    notIn?: number[] | ListIntFieldRefInput<$PrismaModel>
    lt?: number | IntFieldRefInput<$PrismaModel>
    lte?: number | IntFieldRefInput<$PrismaModel>
    gt?: number | IntFieldRefInput<$PrismaModel>
    gte?: number | IntFieldRefInput<$PrismaModel>
    not?: NestedIntFilter<$PrismaModel> | number
  }

  export type FloatFilter<$PrismaModel = never> = {
    equals?: number | FloatFieldRefInput<$PrismaModel>
    in?: number[] | ListFloatFieldRefInput<$PrismaModel>
    notIn?: number[] | ListFloatFieldRefInput<$PrismaModel>
    lt?: number | FloatFieldRefInput<$PrismaModel>
    lte?: number | FloatFieldRefInput<$PrismaModel>
    gt?: number | FloatFieldRefInput<$PrismaModel>
    gte?: number | FloatFieldRefInput<$PrismaModel>
    not?: NestedFloatFilter<$PrismaModel> | number
  }

  export type FloatNullableFilter<$PrismaModel = never> = {
    equals?: number | FloatFieldRefInput<$PrismaModel> | null
    in?: number[] | ListFloatFieldRefInput<$PrismaModel> | null
    notIn?: number[] | ListFloatFieldRefInput<$PrismaModel> | null
    lt?: number | FloatFieldRefInput<$PrismaModel>
    lte?: number | FloatFieldRefInput<$PrismaModel>
    gt?: number | FloatFieldRefInput<$PrismaModel>
    gte?: number | FloatFieldRefInput<$PrismaModel>
    not?: NestedFloatNullableFilter<$PrismaModel> | number | null
  }

  export type SortOrderInput = {
    sort: SortOrder
    nulls?: NullsOrder
  }

  export type BenchmarkCountOrderByAggregateInput = {
    id?: SortOrder
    createdAt?: SortOrder
    cpuModel?: SortOrder
    gpuModel?: SortOrder
    ramGB?: SortOrder
    os?: SortOrder
    codec?: SortOrder
    preset?: SortOrder
    fps?: SortOrder
    vmaf?: SortOrder
    fileSizeBytes?: SortOrder
    notes?: SortOrder
  }

  export type BenchmarkAvgOrderByAggregateInput = {
    ramGB?: SortOrder
    fps?: SortOrder
    vmaf?: SortOrder
    fileSizeBytes?: SortOrder
  }

  export type BenchmarkMaxOrderByAggregateInput = {
    id?: SortOrder
    createdAt?: SortOrder
    cpuModel?: SortOrder
    gpuModel?: SortOrder
    ramGB?: SortOrder
    os?: SortOrder
    codec?: SortOrder
    preset?: SortOrder
    fps?: SortOrder
    vmaf?: SortOrder
    fileSizeBytes?: SortOrder
    notes?: SortOrder
  }

  export type BenchmarkMinOrderByAggregateInput = {
    id?: SortOrder
    createdAt?: SortOrder
    cpuModel?: SortOrder
    gpuModel?: SortOrder
    ramGB?: SortOrder
    os?: SortOrder
    codec?: SortOrder
    preset?: SortOrder
    fps?: SortOrder
    vmaf?: SortOrder
    fileSizeBytes?: SortOrder
    notes?: SortOrder
  }

  export type BenchmarkSumOrderByAggregateInput = {
    ramGB?: SortOrder
    fps?: SortOrder
    vmaf?: SortOrder
    fileSizeBytes?: SortOrder
  }

  export type StringWithAggregatesFilter<$PrismaModel = never> = {
    equals?: string | StringFieldRefInput<$PrismaModel>
    in?: string[] | ListStringFieldRefInput<$PrismaModel>
    notIn?: string[] | ListStringFieldRefInput<$PrismaModel>
    lt?: string | StringFieldRefInput<$PrismaModel>
    lte?: string | StringFieldRefInput<$PrismaModel>
    gt?: string | StringFieldRefInput<$PrismaModel>
    gte?: string | StringFieldRefInput<$PrismaModel>
    contains?: string | StringFieldRefInput<$PrismaModel>
    startsWith?: string | StringFieldRefInput<$PrismaModel>
    endsWith?: string | StringFieldRefInput<$PrismaModel>
    mode?: QueryMode
    not?: NestedStringWithAggregatesFilter<$PrismaModel> | string
    _count?: NestedIntFilter<$PrismaModel>
    _min?: NestedStringFilter<$PrismaModel>
    _max?: NestedStringFilter<$PrismaModel>
  }

  export type DateTimeWithAggregatesFilter<$PrismaModel = never> = {
    equals?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    in?: Date[] | string[] | ListDateTimeFieldRefInput<$PrismaModel>
    notIn?: Date[] | string[] | ListDateTimeFieldRefInput<$PrismaModel>
    lt?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    lte?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    gt?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    gte?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    not?: NestedDateTimeWithAggregatesFilter<$PrismaModel> | Date | string
    _count?: NestedIntFilter<$PrismaModel>
    _min?: NestedDateTimeFilter<$PrismaModel>
    _max?: NestedDateTimeFilter<$PrismaModel>
  }

  export type StringNullableWithAggregatesFilter<$PrismaModel = never> = {
    equals?: string | StringFieldRefInput<$PrismaModel> | null
    in?: string[] | ListStringFieldRefInput<$PrismaModel> | null
    notIn?: string[] | ListStringFieldRefInput<$PrismaModel> | null
    lt?: string | StringFieldRefInput<$PrismaModel>
    lte?: string | StringFieldRefInput<$PrismaModel>
    gt?: string | StringFieldRefInput<$PrismaModel>
    gte?: string | StringFieldRefInput<$PrismaModel>
    contains?: string | StringFieldRefInput<$PrismaModel>
    startsWith?: string | StringFieldRefInput<$PrismaModel>
    endsWith?: string | StringFieldRefInput<$PrismaModel>
    mode?: QueryMode
    not?: NestedStringNullableWithAggregatesFilter<$PrismaModel> | string | null
    _count?: NestedIntNullableFilter<$PrismaModel>
    _min?: NestedStringNullableFilter<$PrismaModel>
    _max?: NestedStringNullableFilter<$PrismaModel>
  }

  export type IntWithAggregatesFilter<$PrismaModel = never> = {
    equals?: number | IntFieldRefInput<$PrismaModel>
    in?: number[] | ListIntFieldRefInput<$PrismaModel>
    notIn?: number[] | ListIntFieldRefInput<$PrismaModel>
    lt?: number | IntFieldRefInput<$PrismaModel>
    lte?: number | IntFieldRefInput<$PrismaModel>
    gt?: number | IntFieldRefInput<$PrismaModel>
    gte?: number | IntFieldRefInput<$PrismaModel>
    not?: NestedIntWithAggregatesFilter<$PrismaModel> | number
    _count?: NestedIntFilter<$PrismaModel>
    _avg?: NestedFloatFilter<$PrismaModel>
    _sum?: NestedIntFilter<$PrismaModel>
    _min?: NestedIntFilter<$PrismaModel>
    _max?: NestedIntFilter<$PrismaModel>
  }

  export type FloatWithAggregatesFilter<$PrismaModel = never> = {
    equals?: number | FloatFieldRefInput<$PrismaModel>
    in?: number[] | ListFloatFieldRefInput<$PrismaModel>
    notIn?: number[] | ListFloatFieldRefInput<$PrismaModel>
    lt?: number | FloatFieldRefInput<$PrismaModel>
    lte?: number | FloatFieldRefInput<$PrismaModel>
    gt?: number | FloatFieldRefInput<$PrismaModel>
    gte?: number | FloatFieldRefInput<$PrismaModel>
    not?: NestedFloatWithAggregatesFilter<$PrismaModel> | number
    _count?: NestedIntFilter<$PrismaModel>
    _avg?: NestedFloatFilter<$PrismaModel>
    _sum?: NestedFloatFilter<$PrismaModel>
    _min?: NestedFloatFilter<$PrismaModel>
    _max?: NestedFloatFilter<$PrismaModel>
  }

  export type FloatNullableWithAggregatesFilter<$PrismaModel = never> = {
    equals?: number | FloatFieldRefInput<$PrismaModel> | null
    in?: number[] | ListFloatFieldRefInput<$PrismaModel> | null
    notIn?: number[] | ListFloatFieldRefInput<$PrismaModel> | null
    lt?: number | FloatFieldRefInput<$PrismaModel>
    lte?: number | FloatFieldRefInput<$PrismaModel>
    gt?: number | FloatFieldRefInput<$PrismaModel>
    gte?: number | FloatFieldRefInput<$PrismaModel>
    not?: NestedFloatNullableWithAggregatesFilter<$PrismaModel> | number | null
    _count?: NestedIntNullableFilter<$PrismaModel>
    _avg?: NestedFloatNullableFilter<$PrismaModel>
    _sum?: NestedFloatNullableFilter<$PrismaModel>
    _min?: NestedFloatNullableFilter<$PrismaModel>
    _max?: NestedFloatNullableFilter<$PrismaModel>
  }

  export type StringFieldUpdateOperationsInput = {
    set?: string
  }

  export type DateTimeFieldUpdateOperationsInput = {
    set?: Date | string
  }

  export type NullableStringFieldUpdateOperationsInput = {
    set?: string | null
  }

  export type IntFieldUpdateOperationsInput = {
    set?: number
    increment?: number
    decrement?: number
    multiply?: number
    divide?: number
  }

  export type FloatFieldUpdateOperationsInput = {
    set?: number
    increment?: number
    decrement?: number
    multiply?: number
    divide?: number
  }

  export type NullableFloatFieldUpdateOperationsInput = {
    set?: number | null
    increment?: number
    decrement?: number
    multiply?: number
    divide?: number
  }

  export type NestedStringFilter<$PrismaModel = never> = {
    equals?: string | StringFieldRefInput<$PrismaModel>
    in?: string[] | ListStringFieldRefInput<$PrismaModel>
    notIn?: string[] | ListStringFieldRefInput<$PrismaModel>
    lt?: string | StringFieldRefInput<$PrismaModel>
    lte?: string | StringFieldRefInput<$PrismaModel>
    gt?: string | StringFieldRefInput<$PrismaModel>
    gte?: string | StringFieldRefInput<$PrismaModel>
    contains?: string | StringFieldRefInput<$PrismaModel>
    startsWith?: string | StringFieldRefInput<$PrismaModel>
    endsWith?: string | StringFieldRefInput<$PrismaModel>
    not?: NestedStringFilter<$PrismaModel> | string
  }

  export type NestedDateTimeFilter<$PrismaModel = never> = {
    equals?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    in?: Date[] | string[] | ListDateTimeFieldRefInput<$PrismaModel>
    notIn?: Date[] | string[] | ListDateTimeFieldRefInput<$PrismaModel>
    lt?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    lte?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    gt?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    gte?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    not?: NestedDateTimeFilter<$PrismaModel> | Date | string
  }

  export type NestedStringNullableFilter<$PrismaModel = never> = {
    equals?: string | StringFieldRefInput<$PrismaModel> | null
    in?: string[] | ListStringFieldRefInput<$PrismaModel> | null
    notIn?: string[] | ListStringFieldRefInput<$PrismaModel> | null
    lt?: string | StringFieldRefInput<$PrismaModel>
    lte?: string | StringFieldRefInput<$PrismaModel>
    gt?: string | StringFieldRefInput<$PrismaModel>
    gte?: string | StringFieldRefInput<$PrismaModel>
    contains?: string | StringFieldRefInput<$PrismaModel>
    startsWith?: string | StringFieldRefInput<$PrismaModel>
    endsWith?: string | StringFieldRefInput<$PrismaModel>
    not?: NestedStringNullableFilter<$PrismaModel> | string | null
  }

  export type NestedIntFilter<$PrismaModel = never> = {
    equals?: number | IntFieldRefInput<$PrismaModel>
    in?: number[] | ListIntFieldRefInput<$PrismaModel>
    notIn?: number[] | ListIntFieldRefInput<$PrismaModel>
    lt?: number | IntFieldRefInput<$PrismaModel>
    lte?: number | IntFieldRefInput<$PrismaModel>
    gt?: number | IntFieldRefInput<$PrismaModel>
    gte?: number | IntFieldRefInput<$PrismaModel>
    not?: NestedIntFilter<$PrismaModel> | number
  }

  export type NestedFloatFilter<$PrismaModel = never> = {
    equals?: number | FloatFieldRefInput<$PrismaModel>
    in?: number[] | ListFloatFieldRefInput<$PrismaModel>
    notIn?: number[] | ListFloatFieldRefInput<$PrismaModel>
    lt?: number | FloatFieldRefInput<$PrismaModel>
    lte?: number | FloatFieldRefInput<$PrismaModel>
    gt?: number | FloatFieldRefInput<$PrismaModel>
    gte?: number | FloatFieldRefInput<$PrismaModel>
    not?: NestedFloatFilter<$PrismaModel> | number
  }

  export type NestedFloatNullableFilter<$PrismaModel = never> = {
    equals?: number | FloatFieldRefInput<$PrismaModel> | null
    in?: number[] | ListFloatFieldRefInput<$PrismaModel> | null
    notIn?: number[] | ListFloatFieldRefInput<$PrismaModel> | null
    lt?: number | FloatFieldRefInput<$PrismaModel>
    lte?: number | FloatFieldRefInput<$PrismaModel>
    gt?: number | FloatFieldRefInput<$PrismaModel>
    gte?: number | FloatFieldRefInput<$PrismaModel>
    not?: NestedFloatNullableFilter<$PrismaModel> | number | null
  }

  export type NestedStringWithAggregatesFilter<$PrismaModel = never> = {
    equals?: string | StringFieldRefInput<$PrismaModel>
    in?: string[] | ListStringFieldRefInput<$PrismaModel>
    notIn?: string[] | ListStringFieldRefInput<$PrismaModel>
    lt?: string | StringFieldRefInput<$PrismaModel>
    lte?: string | StringFieldRefInput<$PrismaModel>
    gt?: string | StringFieldRefInput<$PrismaModel>
    gte?: string | StringFieldRefInput<$PrismaModel>
    contains?: string | StringFieldRefInput<$PrismaModel>
    startsWith?: string | StringFieldRefInput<$PrismaModel>
    endsWith?: string | StringFieldRefInput<$PrismaModel>
    not?: NestedStringWithAggregatesFilter<$PrismaModel> | string
    _count?: NestedIntFilter<$PrismaModel>
    _min?: NestedStringFilter<$PrismaModel>
    _max?: NestedStringFilter<$PrismaModel>
  }

  export type NestedDateTimeWithAggregatesFilter<$PrismaModel = never> = {
    equals?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    in?: Date[] | string[] | ListDateTimeFieldRefInput<$PrismaModel>
    notIn?: Date[] | string[] | ListDateTimeFieldRefInput<$PrismaModel>
    lt?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    lte?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    gt?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    gte?: Date | string | DateTimeFieldRefInput<$PrismaModel>
    not?: NestedDateTimeWithAggregatesFilter<$PrismaModel> | Date | string
    _count?: NestedIntFilter<$PrismaModel>
    _min?: NestedDateTimeFilter<$PrismaModel>
    _max?: NestedDateTimeFilter<$PrismaModel>
  }

  export type NestedStringNullableWithAggregatesFilter<$PrismaModel = never> = {
    equals?: string | StringFieldRefInput<$PrismaModel> | null
    in?: string[] | ListStringFieldRefInput<$PrismaModel> | null
    notIn?: string[] | ListStringFieldRefInput<$PrismaModel> | null
    lt?: string | StringFieldRefInput<$PrismaModel>
    lte?: string | StringFieldRefInput<$PrismaModel>
    gt?: string | StringFieldRefInput<$PrismaModel>
    gte?: string | StringFieldRefInput<$PrismaModel>
    contains?: string | StringFieldRefInput<$PrismaModel>
    startsWith?: string | StringFieldRefInput<$PrismaModel>
    endsWith?: string | StringFieldRefInput<$PrismaModel>
    not?: NestedStringNullableWithAggregatesFilter<$PrismaModel> | string | null
    _count?: NestedIntNullableFilter<$PrismaModel>
    _min?: NestedStringNullableFilter<$PrismaModel>
    _max?: NestedStringNullableFilter<$PrismaModel>
  }

  export type NestedIntNullableFilter<$PrismaModel = never> = {
    equals?: number | IntFieldRefInput<$PrismaModel> | null
    in?: number[] | ListIntFieldRefInput<$PrismaModel> | null
    notIn?: number[] | ListIntFieldRefInput<$PrismaModel> | null
    lt?: number | IntFieldRefInput<$PrismaModel>
    lte?: number | IntFieldRefInput<$PrismaModel>
    gt?: number | IntFieldRefInput<$PrismaModel>
    gte?: number | IntFieldRefInput<$PrismaModel>
    not?: NestedIntNullableFilter<$PrismaModel> | number | null
  }

  export type NestedIntWithAggregatesFilter<$PrismaModel = never> = {
    equals?: number | IntFieldRefInput<$PrismaModel>
    in?: number[] | ListIntFieldRefInput<$PrismaModel>
    notIn?: number[] | ListIntFieldRefInput<$PrismaModel>
    lt?: number | IntFieldRefInput<$PrismaModel>
    lte?: number | IntFieldRefInput<$PrismaModel>
    gt?: number | IntFieldRefInput<$PrismaModel>
    gte?: number | IntFieldRefInput<$PrismaModel>
    not?: NestedIntWithAggregatesFilter<$PrismaModel> | number
    _count?: NestedIntFilter<$PrismaModel>
    _avg?: NestedFloatFilter<$PrismaModel>
    _sum?: NestedIntFilter<$PrismaModel>
    _min?: NestedIntFilter<$PrismaModel>
    _max?: NestedIntFilter<$PrismaModel>
  }

  export type NestedFloatWithAggregatesFilter<$PrismaModel = never> = {
    equals?: number | FloatFieldRefInput<$PrismaModel>
    in?: number[] | ListFloatFieldRefInput<$PrismaModel>
    notIn?: number[] | ListFloatFieldRefInput<$PrismaModel>
    lt?: number | FloatFieldRefInput<$PrismaModel>
    lte?: number | FloatFieldRefInput<$PrismaModel>
    gt?: number | FloatFieldRefInput<$PrismaModel>
    gte?: number | FloatFieldRefInput<$PrismaModel>
    not?: NestedFloatWithAggregatesFilter<$PrismaModel> | number
    _count?: NestedIntFilter<$PrismaModel>
    _avg?: NestedFloatFilter<$PrismaModel>
    _sum?: NestedFloatFilter<$PrismaModel>
    _min?: NestedFloatFilter<$PrismaModel>
    _max?: NestedFloatFilter<$PrismaModel>
  }

  export type NestedFloatNullableWithAggregatesFilter<$PrismaModel = never> = {
    equals?: number | FloatFieldRefInput<$PrismaModel> | null
    in?: number[] | ListFloatFieldRefInput<$PrismaModel> | null
    notIn?: number[] | ListFloatFieldRefInput<$PrismaModel> | null
    lt?: number | FloatFieldRefInput<$PrismaModel>
    lte?: number | FloatFieldRefInput<$PrismaModel>
    gt?: number | FloatFieldRefInput<$PrismaModel>
    gte?: number | FloatFieldRefInput<$PrismaModel>
    not?: NestedFloatNullableWithAggregatesFilter<$PrismaModel> | number | null
    _count?: NestedIntNullableFilter<$PrismaModel>
    _avg?: NestedFloatNullableFilter<$PrismaModel>
    _sum?: NestedFloatNullableFilter<$PrismaModel>
    _min?: NestedFloatNullableFilter<$PrismaModel>
    _max?: NestedFloatNullableFilter<$PrismaModel>
  }



  /**
   * Batch Payload for updateMany & deleteMany & createMany
   */

  export type BatchPayload = {
    count: number
  }

  /**
   * DMMF
   */
  export const dmmf: runtime.BaseDMMF
}