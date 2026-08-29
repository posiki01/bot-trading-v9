"""
config/news_keywords.py
Define palabras clave para el análisis de noticias y sentimiento.
"""

PALABRAS_CLAVE_IMPACTO = {
    'CRITICO': ['war', 'guerra', 'crisis', 'crash', 'recession', 'recesión', 'default', 'impago', 'debt ceiling', 'techo de deuda', 'sovereign debt', 'liquidity crisis', 'nuclear', 'geopolitical risk', 'black swan'],
    'POLITICO': ['election', 'elección', 'sanctions', 'sanciones', 'coup', 'golpe', 'impeachment', 'brexit', 'treaty', 'tratado', 'geopolitical', 'geopolítico', 'conflict', 'conflicto', 'trade war', 'guerra comercial'],
    'ALTO': ['fed', 'central bank', 'banco central', 'interest rate', 'tasa de interés', 'tipos', 'inflation', 'inflación', 'nfp', 'yield spike', 'rating downgrade', 'rebaja de calificación', 'fiscal policy', 'fomc'],
    'MEDIO': ['oil', 'petróleo', 'gold', 'oro', 'commodities', 'materias primas', 'crude', 'crudo', 'natural gas', 'gas natural', 'inventory', 'inventario', 'supply chain', 'opec', 'opep', 'trade', 
               'regulation', 'regulación', 'growth', 'crecimiento', 'pib', 'gdp']
}

KEYWORDS_DIVISAS_NLP = {
    'EUR': ['euro', 'ecb', 'bce', 'lagarde', 'germany', 'alemania', 'france', 'francia', 'ez', 'bruselas', 'european union'],
    'USD': ['dollar', 'dólar', 'fed', 'powell', 'treasury', 'tesoro', 'fomc', 'u.s.', 'ee.uu', 'usd', 'washington', 'united states'],
    'GBP': ['pound', 'libra', 'boe', 'bailey', 'uk', 'london', 'londres', 'britain', 'bretaña', 'sterling', 'england'],
    'JPY': ['yen', 'boj', 'ueda', 'japan', 'japón', 'tokyo', 'nikkei'],
    'AUD': ['aussie', 'rba', 'australia', 'bullock', 'commodity'],
    'CAD': ['loonie', 'boc', 'canada', 'canadá', 'macklem', 'oil', 'petróleo'],
    'CHF': ['franc', 'franco', 'snb', 'bns', 'switzerland', 'suiza', 'zurich', 'bern'],
    'NZD': ['kiwi', 'rbnz', 'new zealand', 'nueva zelanda', 'orr', 'commodity'],
    'BTC': ['bitcoin', 'btc', 'halving', 'etf', 'sec', 'satoshi', 'digital gold', 'crypto', 'cripto', 'blockchain'],
    'ETH': ['ethereum', 'eth', 'vitalik', 'etf', 'sec', 'staking', 'merge', 'layer 2', 'crypto', 'cripto'],
    'SOL': ['solana', 'sol', 'phantom', 'saga', 'crypto', 'cripto'],
    'XAU': ['gold', 'oro', 'xau', 'precious metal'],
    'NAS100': ['nasdaq', 'nas100', 'ndx', 'tech stocks', 'nvidia', 'apple', 'microsoft'],
    'US30': ['dow jones', 'us30', 'dji', 'blue chips'],
    'US500': ['s&p 500', 'spx', 'us500', 'market index']
}