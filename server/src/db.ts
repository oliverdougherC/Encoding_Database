import { PrismaClient } from '@prisma/client';

export const prisma = new PrismaClient({
  transactionOptions: {
    maxWait: 5_000,   // wait for DB connection
    timeout: 15_000,  // max transaction execution time
  },
});

/**
 * Explicitly connect to the database.
 * Call this before starting the HTTP server to ensure
 * the database is reachable and avoid cold-start delays.
 */
export async function connectDatabase(): Promise<void> {
  await prisma.$connect();
  console.log('Database connected successfully');
}

/**
 * Gracefully disconnect from the database.
 */
export async function disconnectDatabase(): Promise<void> {
  await prisma.$disconnect();
  console.log('Database disconnected');
}
