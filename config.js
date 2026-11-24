// App settings. Fill in the two Supabase values from
// Supabase dashboard > Project Settings > API (or "Connect").
// The anon key is meant to be public; the data is protected by login + row-level security.
window.APP_CONFIG = {
  SUPABASE_URL: 'https://eerfbykyngzxwxqgdhfu.supabase.co',
  SUPABASE_ANON_KEY: 'sb_publishable_4bncoZchDlTEqYM8w9rhMA_JEMQ-zb6',

  // Login names are turned into "<name>@<USER_DOMAIN>" for Supabase Auth.
  // Create users in Supabase > Authentication > Users > Add user, e.g. jo@expenses.local
  USER_DOMAIN: 'expenses.local',

  // Shown in front of amounts, e.g. '£' or '€'. Leave '' for none.
  CURRENCY: '฿',

  // Login names that may edit budgets (the database enforces this too)
  BUDGET_EDITORS: ['nigel'],

  // New lines start on this category (saves a tap most of the time)
  DEFAULT_CATEGORY: 'Groceries (food)',

  // The main (budgeted) categories and their starting budgets. The live budgets, with history,
  // are in the database (supabase/budgets.sql); these are only used until it has loaded.
  BUDGETS: {
    'Pocket Money (NIG)': 5000,
    'Pocket Money (JOP)': 5000,
    'Groceries (food)': 14000,
    'Eating Out': 5000,
    'Domestic': 22343,
    'Beer': 6000,
    'Car Expenses': 3000,
    'Cat expenses': 3000,
    'Health expenses': 3000,
    'Digital': 4032.33,
    'Travel and Holiday': 10000,
    'One-off expenses': 2000,
    'Quintara': 15271,
  },

  // Drop-down order
  CATEGORIES: [
    'Groceries (food)',
    'Eating Out',
    'Domestic',
    'Cat expenses',
    'Digital',
    'Health expenses',
    'Beer',
    'Investment (+/-)',
    'Travel and Holiday',
    'Quintara',
    'Pocket Money (JOP)',
    'Pocket Money (NIG)',
    'Car Expenses',
    'One-off expenses',
    'Planned expenses',
    'Charitable expenses',
    'Other',
  ],
};
