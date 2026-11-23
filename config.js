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

  CATEGORIES: [
    'Pocket Money (NIG)',
    'Pocket Money (JOP)',
    'Groceries (food)',
    'Eating Out',
    'Domestic',
    'Beer',
    'Car Expenses',
    'Cat expenses',
    'Health expenses',
    'Digital',
    'Travel and Holiday',
    'One-off expenses',
    'Quintara',
    'Investment (+/-)',
    'Planned expenses',
    'Charitable expenses',
    'Other',
  ],
};
