# D&D Accountant

Tired of sleazy players messing with their gold quantities? Hate math and spreadsheets but want to be able to track any shenanigans that might take place? Love control and the ability to manage every transaction players make with each other and the world? The D&D Accountant can help you out with all of that and more.

## Features
- Players register accounts that only they and the GM can access
- View balance at any time, including counts for each coin, and an EGP value
- Players request transactions through a simple English-like command syntax
- Changes to the players' balance are only reflected after the GM approves transactions
- GM can manually perform most changes to player accounts without going through them
- Automatically perform currency conversions, including conversions using EGP values
- Perform basic dice rolls, including rolls involving multiple dice and offsets

## Usage
Commands are prefixed with `dnd-` (e.g. `dnd-help`). All commands can be listed using `dnd-help`, and each has a detailed usage guide that can be accessed using `dnd-help [command]`, where `[command]` is the command as listed in the help text. 

### Campaign creation
To get started, the GM must create a new channel, and then use the command `dnd-initialize` to set up a campaign. This campaign will be tied to the channel it is created in, and the person who ran the `dnd-initialize` command will have GM privileges. Once a campaign is initialized, the players can use the command `dnd-register [name]` to create an account in that campaign. Initially, their account will have zero balance, which they can view using `dnd-balance`. The balance can only be changed through transactions.

### Transactions and approval
To make transactions, players can use the `dnd-transact` command. This command has a lot of functionality which can be viewed using `dnd-help transact`, but the most basic use to start off with will be to add some starting gold. This command might look something like `dnd-transact take 15 gp for starting gold`. To understand how this works, please consult the help text.

Once players have requested these transactions, the GM will need to approve them to have the gold actually added to the players' accounts. The GM can view pending transactions using the `dnd-pending` command. To approve all transactions, `dnd-approve all` can be used. If only some transactions are to be approved, the transactions to be approved can be specified using their numbers as displayed in the output of the `dnd-pending` command (e.g. `dnd-approve 1, 3, 4`). The same goes for the `dnd-deny` command. To learn more about the ways transactions can be specified, please consult the help text for the `dnd-approve` or `dnd-deny` commands.

### Inter-player transactions
Players can also perform transactions with other players by specifying the name that player registered themselves in the campaign with. This uses the same `dnd-transact` command, though with a slightly different syntax. Again, it is best to consult the help text, but an example use might be something like `dnd-transact give 15 gp to PlayerName for used scale mail`, where PlayerName is the registered name of a player (not their discord name). Note that in addition to the GM, inter-player transactions can also be approved by the player at the receiving end. In the above case, PlayerName could have used `dnd-pending` and `dnd-approve all` to approve this transaction.

### Further usage
This usage guide does not cover a lot of the functionality of the bot, such as the dice roll (`dnd-roll`) and currency conversion (`dnd-convert`), as well as additional functionality of many of these commands. To learn about these features and more, please refer to the help text of each command. Even if you do not intend to use these features, there are some idiosyncrasies of the discussed commands, such as the case sensitivity and no space requirements of the `dnd-register` command that you should know about.
