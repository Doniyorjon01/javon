# ruff: noqa: E501  (one book per line reads better than wrapped tuples)
"""
Starter books for the shared catalog
====================================
    python -m scripts.seed_starter_books            # from the project root
    python -m scripts.seed_starter_books --dry-run  # check, write nothing

A first set of books so a new store's search finds something on day one; after
that the catalog grows by itself from what stores add (every non-rejected book
is visible to all stores).

  * STARTER_BOOKS: well-known books with an ISBN. Each ISBN was checked against
    its Open Library edition page (openlibrary.org/isbn/<ISBN>, October 2026):
    title, author, publisher and pages are that edition's; the year is left
    empty where the record looked unreliable.
  * UZBEK_CLASSICS: Uzbek classics without an ISBN. They have many editions
    (most without an ISBN), so the entry is the work itself; a store that sells
    a particular edition with an ISBN can add that edition too.

Same rules as scripts/seed_catalog.py (which does the work): books are added as
APPROVED with no submitting store, and running it again skips what is already
in the catalog (same ISBN, or the same title/authors/language/script).
"""

import argparse
import asyncio
import sys

from database.config import engine
from scripts.seed_catalog import Report, load_rows

Row = dict[str, str | None]

# fmt: off
# (isbn, title, authors separated by ";", publisher, published_year, pages)
_EN: list[tuple[str, str, str, str, str, str]] = [
    ("9780451524935", "1984", "George Orwell", "Signet Classic", "", ""),
    ("9780451526342", "Animal Farm", "George Orwell", "Signet Classics", "1996", "140"),
    ("9780061120084", "To Kill a Mockingbird", "Harper Lee", "Harper Perennial Modern Classics", "2006", "323"),
    ("9780743273565", "The Great Gatsby", "F. Scott Fitzgerald", "Scribner", "2004", "180"),
    ("9780062315007", "The Alchemist", "Paulo Coelho", "HarperOne", "2014", "208"),
    ("9780062316097", "Sapiens: A Brief History of Humankind", "Yuval Noah Harari", "Harper", "2015", ""),
    ("9780735211292", "Atomic Habits", "James Clear", "Avery", "2018", "320"),
    ("9780156012195", "The Little Prince", "Antoine de Saint-Exupéry", "Harcourt", "2000", "96"),
    ("9780590353427", "Harry Potter and the Sorcerer's Stone", "J. K. Rowling", "Scholastic", "1999", "309"),
    ("9780141439518", "Pride and Prejudice", "Jane Austen", "Penguin Classics", "2003", "435"),
    ("9780486415871", "Crime and Punishment", "Fyodor Dostoevsky", "Dover Publications", "2001", "430"),
    ("9780374528379", "The Brothers Karamazov", "Fyodor Dostoevsky", "Farrar, Straus and Giroux", "2002", "824"),
    ("9780316769488", "The Catcher in the Rye", "J. D. Salinger", "Little, Brown and Company", "1991", ""),
    ("9780374533557", "Thinking, Fast and Slow", "Daniel Kahneman", "Farrar, Straus and Giroux", "2013", "499"),
    ("9781612680194", "Rich Dad Poor Dad", "Robert T. Kiyosaki", "Plata Publishing", "", "301"),
    ("9780743269513", "The 7 Habits of Highly Effective People", "Stephen R. Covey", "Free Press", "2004", "384"),
    ("9780671027032", "How to Win Friends and Influence People", "Dale Carnegie", "Pocket Books", "1998", "320"),
    ("9780812981605", "The Power of Habit", "Charles Duhigg", "Random House", "2012", "371"),
    ("9780807014271", "Man's Search for Meaning", "Viktor E. Frankl", "Beacon Press", "2006", "165"),
    ("9780547928227", "The Hobbit", "J. R. R. Tolkien", "Mariner Books", "2012", "300"),
    ("9780544003415", "The Lord of the Rings", "J. R. R. Tolkien", "Houghton Mifflin Harcourt", "2012", "1216"),
    ("9781455586691", "Deep Work", "Cal Newport", "Grand Central Publishing", "2016", "295"),
    ("9780857197689", "The Psychology of Money", "Morgan Housel", "Harriman House", "2020", "250"),
    ("9781585424337", "Think and Grow Rich", "Napoleon Hill", "Jeremy P. Tarcher/Penguin", "2005", "302"),
    ("9781591846444", "Start with Why", "Simon Sinek", "Portfolio", "2011", "256"),
    ("9780804139298", "Zero to One", "Peter Thiel; Blake Masters", "Crown Business", "2014", "195"),
    ("9780307887894", "The Lean Startup", "Eric Ries", "Crown Business", "2011", "336"),
    ("9780066620992", "Good to Great", "Jim Collins", "HarperBusiness", "2001", "300"),
    ("9781451648539", "Steve Jobs", "Walter Isaacson", "Simon & Schuster", "2011", "630"),
    ("9780060850524", "Brave New World", "Aldous Huxley", "Harper Perennial Modern Classics", "2006", ""),
    ("9780684801223", "The Old Man and the Sea", "Ernest Hemingway", "Scribner", "", "128"),
    ("9780140177398", "Of Mice and Men", "John Steinbeck", "Penguin Books", "1993", "107"),
    ("9780141441146", "Jane Eyre", "Charlotte Brontë", "Penguin Classics", "2006", "578"),
    ("9780141439556", "Wuthering Heights", "Emily Brontë", "Penguin Classics", "2002", "416"),
    ("9780143035008", "Anna Karenina", "Leo Tolstoy", "Penguin Classics", "2004", "838"),
    ("9781400079988", "War and Peace", "Leo Tolstoy", "Vintage Classics", "", "1273"),
    ("9780060883287", "One Hundred Years of Solitude", "Gabriel García Márquez", "Harper Perennial Modern Classics", "2006", "448"),
    ("9781594631931", "The Kite Runner", "Khaled Hosseini", "Riverhead Books", "2013", "400"),
    ("9781594483851", "A Thousand Splendid Suns", "Khaled Hosseini", "Riverhead Books", "2008", ""),
    ("9780375842207", "The Book Thief", "Markus Zusak", "Alfred A. Knopf", "2007", "566"),
    ("9780307474278", "The Da Vinci Code", "Dan Brown", "Anchor", "2009", "608"),
    ("9780143130727", "Ikigai", "Héctor García; Francesc Miralles", "Penguin Life", "2017", "194"),
    ("9781878424310", "The Four Agreements", "Don Miguel Ruiz", "Amber-Allen Publishing", "1997", "140"),
    ("9780062515674", "The Monk Who Sold His Ferrari", "Robin Sharma", "HarperSanFrancisco", "1998", "198"),
    ("9781524763138", "Becoming", "Michelle Obama", "Crown", "2018", "448"),
    ("9780316017930", "Outliers", "Malcolm Gladwell", "Little, Brown and Company", "2011", "336"),
    ("9780060555665", "The Intelligent Investor", "Benjamin Graham", "HarperBusiness", "2006", ""),
    ("9780132350884", "Clean Code", "Robert C. Martin", "Prentice Hall", "2008", "431"),
    ("9780135957059", "The Pragmatic Programmer", "David Thomas; Andrew Hunt", "Addison-Wesley", "2019", "352"),
    ("9780441172719", "Dune", "Frank Herbert", "Ace Books", "1987", "535"),
    ("9780141180144", "The Master and Margarita", "Mikhail Bulgakov", "Penguin Books", "", "411"),
    ("9780140449266", "The Count of Monte Cristo", "Alexandre Dumas", "Penguin Classics", "2003", "1276"),
    ("9780060934347", "Don Quixote", "Miguel de Cervantes", "Harper Perennial", "2005", "992"),
    ("9781846590320", "Jamilia", "Chingiz Aitmatov", "Telegram Books", "2008", "96"),
    ("9780578467290", "Bygone Days", "Abdulla Qodiriy", "Suhbat LLC", "2019", "667"),
]

# (title, author): Uzbek classics, no ISBN (see the module docstring).
_UZ: list[tuple[str, str]] = [
    ("O'tkan kunlar", "Abdulla Qodiriy"),
    ("Mehrobdan chayon", "Abdulla Qodiriy"),
    ("Kecha va kunduz", "Abdulhamid Cho'lpon"),
    ("Shum bola", "G'afur G'ulom"),
    ("Sariq devni minib", "Xudoyberdi To'xtaboyev"),
    ("Dunyoning ishlari", "O'tkir Hoshimov"),
    ("Ikki eshik orasi", "O'tkir Hoshimov"),
    ("Navoiy", "Oybek"),
    ("Sarob", "Abdulla Qahhor"),
    ("Yulduzli tunlar", "Pirimqul Qodirov"),
    ("Ufq", "Said Ahmad"),
    ("Boburnoma", "Zahiriddin Muhammad Bobur"),
]
# fmt: on

STARTER_BOOKS: list[Row] = [
    {
        "isbn": isbn,
        "title": title,
        "authors": authors,
        "publisher": publisher,
        "published_year": year,
        "pages": pages,
        "language": "en",
        "script": "latn",
    }
    for isbn, title, authors, publisher, year, pages in _EN
]

UZBEK_CLASSICS: list[Row] = [
    {"title": title, "authors": author, "language": "uz", "script": "latn"} for title, author in _UZ
]


async def load(*, dry_run: bool = False) -> Report:
    return await load_rows(STARTER_BOOKS + UZBEK_CLASSICS, dry_run=dry_run)


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Add the starter books to the javon catalog.")
    parser.add_argument("--dry-run", action="store_true", help="validate only, write nothing")
    args = parser.parse_args(argv)
    try:
        report = await load(dry_run=args.dry_run)
    finally:
        await engine.dispose()

    verb = "would be added" if args.dry_run else "added"
    print(f"{report.added} {verb}, {report.skipped} already in the catalog, {len(report.errors)} errors")
    for error in report.errors:
        print("  " + error, file=sys.stderr)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
