import asyncio
import logging
import math
import os
import pickle
import random

import discord
from discord.ext import commands

FORMAT = '%(levelname)s:%(name)s:(%(asctime)s): %(message)s'
DATEFMT = '%d-%b-%y %H:%M:%S'
logging.basicConfig(format = FORMAT, datefmt = DATEFMT, level = logging.INFO)

bot = commands.Bot('dnd-')

RESERVED_NAMES = {'World', 'all'}
CONVERSIONS = {'cp': 1, 'sp': 10, 'gp': 100, 'pp': 1000}

################################################################################
#Internal classes and functions start

class Campaign:
    def __init__(self, id, gm):
        self.VERSION = '1.0'
        self.names = {}
        self.players = {}
        self.pending = []
        self.archive = []
        self.id = id
        self.gms = [gm]


    def approve(self, indices):
        for index in indices:
            self.pending[index].complete()
            self.archive.append(self.pending[index])
        self.pending = [item for index, item in enumerate(self.pending)
                        if index not in indices]


    def deny(self, indices):
        self.pending = [item for index, item in enumerate(self.pending)
                        if index not in indices]



class Player:
    def __init__(self, id, name):
        self.cp = 0
        self.sp = 0
        self.gp = 0
        self.pp = 0
        self.id = id
        self.name = name


    @property
    def balance(self):
        coins =  '[{0.cp} CP | {0.sp} SP | {0.gp} GP | {0.pp} PP]'.format(self)
        egp = ' ({0:.2f} EGP)'.format(convert_to_egp({
            'cp': self.cp,
            'sp': self.sp,
            'gp': self.gp,
            'pp': self.pp,
        }))
        return coins + egp



class Transaction:
    def __init__(self, initiator, mode, amounts, participant, reason):
        self.participant = participant
        self.initiator = initiator
        self.amounts = amounts
        self.reason = reason
        self.mode = mode

        if participant is None:
            self.participant = Player(None, 'World')


    def complete(self):
        if self.mode == 'give':
            mult = -1
        elif self.mode == 'take':
            mult = 1

        for coin in self.amounts:
            val = getattr(self.initiator, coin) + self.amounts[coin]*mult
            setattr(self.initiator, coin, val)

        if self.participant.name:
            for coin in self.amounts:
                val = getattr(self.participant, coin) - self.amounts[coin]*mult
                setattr(self.participant, coin, val)


    @property
    def text(self):
        initiator = self.initiator.name

        if self.mode == 'give':
            arrow = '->'
        elif self.mode == 'take':
            arrow = '<-'
        else:
            raise ValueError('Mode should be "give" or "take"')

        amount = ''
        for coin in self.amounts:
            if self.amounts[coin]:
                amount += str(self.amounts[coin]) + ' ' + coin.upper() + ', '
        amount = amount[ :-2]

        if not self.reason:
            reason = 'No reason given'
        else:
            reason = self.reason

        participant = self.participant.name

        return f'{initiator} {arrow} {participant}: {amount} ({reason})'



class DatabaseManager:
    def __init__(self):
        self.campaigns = [int(id) for id in os.listdir('data')]
        self.locks = {int(id): asyncio.Lock() for id in os.listdir('data')}
        self.cache = {}


    async def add_campaign(self, campaign):
        if campaign.id in self.campaigns:
            raise FileExistsError('Campaign with this ID already exists')

        logging.info('Created {0}'.format(campaign.id))

        self.campaigns.append(campaign.id)
        self.locks[campaign.id] = asyncio.Lock()

        await self.locks[campaign.id].acquire()
        await self.save_campaign(campaign)


    async def load_campaign(self, id, blocking = False):
        await self.locks[id].acquire()

        if id not in self.cache:
            logging.info('Reading {0}'.format(id))
            try:
                with open('data/{0}'.format(id), 'rb') as file:
                    campaign = pickle.load(file)
            except FileNotFoundError:
                return None
            self.cache[campaign.id] = campaign
            while len(self.cache) > 10:
                self.cache.pop(self.cache.keys()[0])

        if not blocking:
            self.locks[id].release()
        else:
            logging.info('Acquired lock for {0}'.format(id))

        return self.cache[id]


    async def save_campaign(self, campaign):
        logging.info('Writing {0}'.format(campaign.id))
        with open('data/{0}'.format(campaign.id), 'wb') as file:
            pickle.dump(campaign, file)
        self.cache[campaign.id] = campaign
        while len(self.cache) > 10:
            self.cache.pop(self.cache.keys()[0])
        self.locks[campaign.id].release()
        logging.info('Released lock for {0}'.format(campaign.id))



async def parse_indices(ctx, campaign, terms):
    pending = [transaction for transaction in campaign.pending
               if ctx.author.id in (transaction.participant.id, *campaign.gms)]
    terms = [term.strip() for term in terms.split(',')]
    indices = []
    if 'last' in terms:
        indices.append(len(pending) - 1)
    elif 'all' in terms:
        indices = [i for i in range(len(pending))]
    else:
        for term in terms:
            term = term.split('-')
            if len(term) == 1:
                try:
                    index = int(term[0]) - 1
                except ValueError:
                    await log_syntax_error(ctx)
                    return None
                if index < len(pending):
                    if index not in indices:
                        indices.append(index)
                else:
                    logging.info('Encountered invalid index; aborting.')
                    await ctx.send('"' + term[0] + '" is an invalid ID.')
                    return None
            elif len(term) == 2:
                try:
                    start_index = int(term[0]) - 1
                    end_index = int(term[1]) - 1
                except ValueError:
                    await log_syntax_error(ctx)
                    return None
                if start_index < end_index:
                    if start_index >= 0 and end_index < len(pending):
                        for i in range(start_index, end_index + 1):
                            if i not in indices:
                                indices.append(i)
                    else:
                        if start_index < 0:
                            problem = str(start_index + 1)
                        else:
                            problem = str(end_index + 1)
                        logging.info('Encountered invalid index; aborting.')
                        await ctx.send('"' + problem + '" is an invalid ID.')
                        return None
                else:
                    logging.info('Encountered invalid slice; aborting.')
                    await ctx.send('Start ID must be lower than end ID.')
                    return None
            else:
                await log_syntax_error(ctx)
                return None
    player_index = 0
    corrected_indices = []
    for global_index, transaction in enumerate(campaign.pending):
        if ctx.author.id in (transaction.participant.id, *campaign.gms):
            if player_index in indices:
                corrected_indices.append(global_index)
            player_index += 1
    corrected_indices.sort()
    return corrected_indices


async def log_syntax_error(ctx):
    logging.info('Invalid syntax; aborting.')
    await ctx.send(':x: Invalid syntax. Use `dnd-help [command]` to view info.')


def convert_to_egp(amounts):
    return (0.01*amounts['cp'] + 0.1*amounts['sp']
            + 1*amounts['gp'] + 10*amounts['pp'])


def convert_from_egp(amount, amounts = None):
    if amounts is None:
        amounts = {'cp': 0, 'sp': 0, 'gp': 0, 'pp': 0}
    amounts['gp'] += int(amount)
    amount = round(10*(amount % 1), 1)
    amounts['sp'] += int(amount)
    amount = round(10*(amount % 1))
    amounts['cp'] += int(amount)
    return amounts

#Internal classes and functions end
################################################################################
#Commands start

brief_desc = 'Initialize a new campaign in the current channel'
full_desc = ('Usage: dnd-initialize\n\n'
             'Initialize a new campaign in the current channel and prepare it '
             'for processing transactions. The user invoking this command '
             'becomes the GM of this campaign and has administrative powers.'
             '\n\nAfter using this command, you should register players or get'
             'them to register using the dnd-register command.')

@bot.command(brief = brief_desc, description = full_desc)
async def initialize(ctx):
    logging.info('Initializing new campaign in #{0}.'.format(ctx.channel.name))

    if os.path.isfile('data/{0}'.format(ctx.channel.id)):
        logging.info('Campaign already exists; aborting.')
        await ctx.send('Campaign already exists in this channel.')
        return

    await dbm.add_campaign(Campaign(ctx.channel.id, ctx.author.id))

    logging.info('Initialization successful.')
    await ctx.send('New campaign initialized.'
                   'Register players with `dnd-register`.')

################################################################################

brief_desc = 'Register a user in the campaign under the given name'
full_desc = ('Usage: dnd-register ([user ID]) as [name]\n\n'
             'Register the user in the campaign as [name] and initialize their '
             'account with zero balance.\n\nOnly the GM may use the optional '
             '([user ID]) argument. When this argument is not supplied, the '
             'user calling this command is registered under the given name.'
             '[name] is case sensitive, and may not contain spaces.')

@bot.command(brief = brief_desc, description = full_desc)
async def register(ctx):
    logging.info('Registering new player in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in dbm.campaigns:
        logging.info('No campaign exists in this channel; aborting.')
        await ctx.send('No campaign exists in this channel.')
        return

    try:
        arguments = ctx.message.content.split(' ')
        if arguments[1] == 'as':
            id = ctx.author.id
            name = arguments[2]
        elif arguments[2] == 'as':
            id = int(arguments[1])
            name = arguments[3]
        else:
            raise IndexError('Invalid syntax')
    except IndexError:
        await log_syntax_error(ctx)
        return

    campaign = await dbm.load_campaign(ctx.channel.id, blocking = False)

    if id in campaign.players:
        name = campaign.players[id].name
        logging.info('Name already exists in campaign; aborting.')
        await ctx.send('You are already registered as {0}.'.format(name))
        return

    if name in campaign.names:
        logging.info('Name already exists in campaign; aborting.')
        await ctx.send('That name is already taken.')
        return

    if name in RESERVED_NAMES:
        logging.info('Name is a reserved keyword; aborting.')
        await ctx.send('That name is a reserved keyword.')
        return

    campaign = await dbm.load_campaign(ctx.channel.id, blocking = True)

    campaign.players[id] = Player(id, name)
    campaign.names[name] = id

    await dbm.save_campaign(campaign)

    logging.info('Player "{0}" successfully registered.'.format(name))
    await ctx.send('Successfully registered {0}.'.format(name))

################################################################################

brief_desc = 'Change the name under which a player is registered'
full_desc = ('Usage: dnd-reregister ([user ID]) as [name]\n\n'
             'Reregister the user in the campaign as [name] retaining their '
             'current account balance.\n\nOnly the GM may use the optional '
             '([user ID]) argument. When this argument is not supplied, the '
             'user calling this command is reregistered under the given name.'
             '[name] is case sensitive, and may not contain spaces.')

@bot.command(brief = brief_desc, description = full_desc)
async def reregister(ctx):
    logging.info('Reregistering new player in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in dbm.campaigns:
        logging.info('No campaign exists in this channel; aborting.')
        await ctx.send('No campaign exists in this channel.')
        return

    try:
        arguments = ctx.message.content.split(' ')
        if arguments[1] == 'as':
            id = ctx.author.id
            name = arguments[2]
        elif arguments[2] == 'as':
            id = int(arguments[1])
            name = arguments[3]
        else:
            raise IndexError('Invalid syntax')
    except IndexError:
        await log_syntax_error(ctx)
        return

    campaign = await dbm.load_campaign(ctx.channel.id, blocking = False)

    if id not in campaign.players:
        logging.info('User is not currently registered; aborting.')
        await ctx.send('You are not registered in this campaign.')
        return

    if name in campaign.names:
        logging.info('Name already exists in campaign; aborting.')
        await ctx.send('That name is already taken.')
        return

    if name in RESERVED_NAMES:
        logging.info('Name is a reserved keyword; aborting.')
        await ctx.send('That name is a reserved keyword.')
        return

    campaign = await dbm.load_campaign(ctx.channel.id, blocking = True)

    del campaign.names[campaign.players[id].name]
    campaign.players[id].name = name
    campaign.names[name] = id
    
    await dbm.save_campaign(campaign)

    logging.info('Player "{0}" successfully reregistered.'.format(name))
    await ctx.send('Successfully reregistered as {0}.'.format(name))

################################################################################

brief_desc = 'Convert a player\'s money between different currencies'
full_desc = ('Usage: dnd-convert (as [initiator name]) [amounts]\n\nWithout '
             'requiring authentication or GM approval, perform the specified '
             'conversions in the caller\'s account internally.\n\n[amounts] is '
             'a collection of comma separated values, with each consisting '
             'of an integer, followed by the unit to convert from, followed by '
             'the keyword "to", followed by the unit to convert to. The units '
             'may be any of CP, SP, GP, or PP. When converting up, the amount '
             'to be converted must be an integer in the target unit. Only the '
             'GM may use the (as [initiator name]) argument to specify the '
             'conversion to take place in the account of [initiator name]')

@bot.command(brief = brief_desc, description = full_desc)
async def convert(ctx):
    logging.info('Performing conversion in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in dbm.campaigns:
        logging.info('No campaign exists in this channel; aborting.')
        await ctx.send('No campaign exists in this channel.')
        return

    try:
        arguments = ctx.message.content.split(' ', maxsplit = 1)[1].split(',')
    except IndexError:
        await log_syntax_error(ctx)
        return

    campaign = await dbm.load_campaign(ctx.channel.id, blocking = False)

    if arguments[0].strip().split(' ', maxsplit = 1)[0] == 'as':
        if ctx.author.id in campaign.gms:
            _kw, name, arguments[0] = arguments[0].split(' ', maxsplit = 2)
            if name in campaign.names:
                initiator = campaign.players[campaign.names[name]]
            else:
                logging.info('Invalid initiator name; aborting.')
                await ctx.send('No player with name "{0}"'.format(name)
                               + ' exists in this campaign.')
                return
        else:
            logging.info('Unauthorized use of "as"; aborting.')
            await ctx.send('You are not authorized to use "as".')
            return
    else:
        if ctx.author.id in campaign.players:
            initiator = campaign.players[ctx.author.id]
        else:
            logging.info('Unregistered user; aborting.')
            await ctx.send('You are not registered in this campaign.')
            return

    amounts = {'cp': 0, 'sp': 0, 'gp': 0, 'pp': 0}
    for argument in arguments:
        try:
            starting, target_unit = argument.lower().split(' to ')
            starting_amt, starting_unit = starting.strip().split(' ')
            starting_amt = int(starting_amt)
            conv_factor = CONVERSIONS[starting_unit]/CONVERSIONS[target_unit]
            if not (starting_amt*conv_factor).is_integer():
                logging.info('Invalid up-conversion; aborting.')
                await ctx.send('Cannot convert {0} {1} to {2}.'.format(
                    starting_amt, starting_unit.upper(), target_unit.upper()))
                return
            amounts[starting_unit] -= starting_amt
            amounts[target_unit] += int(starting_amt*conv_factor)
        except (IndexError, ValueError):
            await log_syntax_error(ctx)
            return

    campaign = await dbm.load_campaign(ctx.channel.id, blocking = True)
    
    transaction = Transaction(initiator, 'take', amounts, None, 'conversion')
    transaction.complete()

    await dbm.save_campaign(campaign)

    logging.info('Conversion successful.')
    await ctx.send('Successfully converted currency.')

################################################################################

brief_desc = 'Make a transaction request and add it to the queue'
full_desc = ('Usage: dnd-transact (as [initiator name]) give/take [amounts] '
             '(at [+/-][offset]%) (to/from [participant name]) (for [reason])'
             '\n\nAdd a transaction request to the queue for adding or '
             'subtracting the given [amounts] to the involved parties\' '
             'accounts.\n\nOnly the GM may use the optional (as [initiator '
             'name]) argument. When this argument is not supplied, the user '
             'calling this command is made the initiator of the transaction. '
             '\n\nThe required argument give/take [amounts] decides whether '
             'the money is credited to or debited from the initiator\'s '
             'account. [amounts] is a collection of comma separated values '
             'consisting of a number followed by the unit, which may be one of '
             'CP, SP, GP, PP, or EGP. Capitalisation is not required. For '
             'example, "give 400 sp", "take 2 CP, 5 SP", and "give 24.5 EGP" '
             'are all syntactically valid. Note that only EGP values can be '
             'non-integers, and only up to two decimal points.\n\nThe optional '
             'argument (at [+/-][offset]%) allows for adding a percentage '
             'offset to the transaction for the purposes of discounts and '
             'price hikes. [+/-][offset] is a signed integer that determines '
             'the type and magnitude of the offset. For example, "+5%" and '
             '"-20%" are both syntactically valid.\n\nThe optional argument '
             '(to/from [participant name]) designates the other participant in '
             'the transaction, if one exists. When this argument is not '
             'supplied, the other participant is assumed to be an NPC or other '
             'similar entity, and hence the money is practically created or '
             'destroyed. Note that the to/from term must be consistent with '
             'the preceding give/take term in order to be syntactically valid. '
             '\n\nThe optional argument (for [reason]) allows for adding a '
             'note to the transaction for record keeping and ease of '
             'identification. [reason] can be an arbitrarily long string, '
             'though it is recommended that it be kept brief for clarity. '
             '\n\nA complete use of the command leveraging all the arguments '
             'may look as follows:\ndnd-transact as player1 give 45 gp at -20% '
             'to player2 for buying used scale mail')

@bot.command(brief = brief_desc, description = full_desc)
async def transact(ctx):
    logging.info('Attempting transaction in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in dbm.campaigns:
        logging.info('Campaign is not initialized; aborting.')
        await ctx.send('No campaign exists in this channel.')
        return

    keywords = {'as', 'give', 'take', 'at', 'to', 'from', 'for'}
    arguments = ctx.message.content.split(' ')[-1:0:-1]
    active_kw = arguments.pop()

    if active_kw not in keywords:
        await log_syntax_error(ctx)
        return

    parsed_args = {}
    while arguments:
        argument = arguments.pop()
        if active_kw == 'for':
            parsed_args[active_kw] = argument
            while arguments:
                parsed_args[active_kw] += ' ' + arguments.pop()
        elif argument in keywords:
            active_kw = argument
        elif active_kw in parsed_args:
            parsed_args[active_kw] += ' ' + argument
        else:
            parsed_args[active_kw] = argument

    campaign = await dbm.load_campaign(ctx.channel.id, blocking = False)

    if 'as' in parsed_args:
        if ctx.author.id in campaign.gms:
            name = parsed_args['as']
            if name in campaign.names:
                initiator = campaign.players[campaign.names[name]]
            else:
                logging.info('Invalid initiator name; aborting.')
                await ctx.send('No player with name "{0}"'.format(name)
                               + ' exists in this campaign.')
                return
        else:
            logging.info('Unauthorized use of "as"; aborting.')
            await ctx.send('You are not authorized to use "as".')
            return
    else:
        if ctx.author.id in campaign.players:
            initiator = campaign.players[ctx.author.id]
        else:
            logging.info('Unregistered user; aborting.')
            await ctx.send('You are not registered in this campaign.')
            return

    if 'give' in parsed_args:
        mode = 'give'
    elif 'take' in parsed_args:
        mode = 'take'
    else:
        await log_syntax_error(ctx)
        return

    amounts = {'cp': 0, 'sp': 0, 'gp': 0, 'pp': 0}
    intake = [term.strip() for term in parsed_args[mode].split(',')]
    for term in intake:
        term = term.split(' ')
        try:
            amount = float(term[0])
        except ValueError:
            await log_syntax_error(ctx)
            return
        if term[1].lower() in amounts:
            amounts[term[1].lower()] += int(amount)
        elif term[1].lower() == 'egp':
            convert_from_egp(amount, amounts)
        else:
            await log_syntax_error(ctx)
            return

    if 'at' in parsed_args:
        intake = parsed_args['at']
        try:
            amount = int(intake[1:-1])
        except ValueError:
            await log_syntax_error(ctx)
            return
        if intake[0] == '+':
            mult = 1
        elif intake[0] == '-':
            mult = -1
        else:
            await log_syntax_error(ctx)
            return
        egp_eq = convert_to_egp(amounts)
        egp_eq = egp_eq*(1 + 0.01*amount*mult)
        amounts = convert_from_egp(egp_eq)

    if 'to' in parsed_args:
        if mode == 'give':
            intake = parsed_args['to']
            participant = True
        else:
            await log_syntax_error(ctx)
            return
    elif 'from' in parsed_args:
        if mode == 'take':
            intake = parsed_args['from']
            participant = True
        else:
            await log_syntax_error(ctx)
            return
    else:
        participant = False

    if participant:
        if intake in campaign.names:
            participant = campaign.players[campaign.names[intake]]
        else:
            logging.info('Invalid participant name; aborting.')
            await ctx.send('No player with name "{0}"'.format(initiator)
                           + ' exists in this campaign.')
            return
    else:
        participant = None

    if 'for' in parsed_args:
        reason = parsed_args['for']
    else:
        reason = None

    campaign = await dbm.load_campaign(ctx.channel.id, blocking = True)

    transaction = Transaction(initiator, mode, amounts, participant, reason)
    campaign.pending.append(transaction)

    await dbm.save_campaign(campaign)

    logging.info('Successfully added transaction to queue.')
    await ctx.send('Transaction recorded; waiting for approval.')

################################################################################

brief_desc = 'View transactions that are waiting for approval'
full_desc = ('Usage: dnd-pending\n\n'
             'Show all transactions that can be approved by the user calling '
             'this command. Note that only the participant in the transaction '
             '(not the initiator) can approve pending transactions, with only '
             'the GM being able to view (and approve) all transactions.')

@bot.command(brief = brief_desc, description = full_desc)
async def pending(ctx):
    logging.info('Displaying pending in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in dbm.campaigns:
        logging.info('Campaign is not initialized; aborting.')
        await ctx.send('No campaign exists in this channel.')
        return

    campaign = await dbm.load_campaign(ctx.channel.id)

    msg = ''
    id = 1
    for transaction in campaign.pending:
        if ctx.author.id in (transaction.participant.id, *campaign.gms):
            msg += str(id) + ': `' + transaction.text + '`\n'
            id += 1
    msg = msg[ :-1]

    if not msg:
        logging.info('No pending transactions.')
        await ctx.send('You have no pending transactions.')
    else:
        logging.info('Transactions successfully displayed.')
        await ctx.send('Pending transactions:\n' + msg)

################################################################################

brief_desc = 'Approve a transaction currently in the queue'
full_desc = ('Usage: dnd-approve [IDs and slices]\n\n'
             'Approve pending transactions with the given IDs and those '
             'contained within the ID slices. The IDs can be obtained by using '
             'the dnd-pending command. The [IDs and slices] argument is a set '
             'of comma separated values containing either IDs or ID slices. An '
             'ID slice consists of a lower ID bound followed by a hyphen and a '
             'upper ID bound, and selects the bounding IDs as well as all IDs '
             'between them. For example, "1, 2, 4", "2-5, 7", and "1-3, 6-7" '
             'are all syntactically valid. "all" and "last" are keywords that'
             'additionally add the respective transactions to the list.')

@bot.command(brief = brief_desc, description = full_desc)
async def approve(ctx):
    logging.info('Approving transactions in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in dbm.campaigns:
        logging.info('Campaign is not initialized; aborting.')
        await ctx.send('No campaign exists in this channel.')
        return

    campaign = await dbm.load_campaign(ctx.channel.id, blocking = False)

    try:
        terms = ctx.message.content.split(' ', 1)[1].strip()
        approved_indices = await parse_indices(ctx, campaign, terms)
    except IndexError:
        await log_syntax_error(ctx)
        return

    if approved_indices is None:
        return
    elif not approved_indices:
        logging.info('No accessible transactions; aborting.')
        await ctx.send('Invalid indicies or no pending transactions.')

    campaign = await dbm.load_campaign(ctx.channel.id, blocking = True)

    campaign.approve(approved_indices)

    await dbm.save_campaign(campaign)

    logging.info('Successfully approved transactions.')
    await ctx.send('Transaction(s) successfully approved.')

################################################################################

brief_desc = 'Deny a transaction currently in the queue'
full_desc = ('Usage: dnd-deny [IDs and slices]\n\n'
             'Deny pending transactions with the given IDs and those contained '
             'within the ID slices. The IDs can be obtained by using the '
             'dnd-pending command. The [IDs and slices] argument is a set '
             'of comma separated values containing either IDs or ID slices. An '
             'ID slice consists of a lower ID bound followed by a hyphen and a '
             'upper ID bound, and selects the bounding IDs as well as all IDs '
             'between them. For example, "1, 2, 4", "2-5, 7", and "1-3, 6-7" '
             'are all syntactically valid. "all" and "last" are keywords that'
             'additionally add the respective transactions to the list.')

@bot.command(brief = brief_desc, description = full_desc)
async def deny(ctx):
    logging.info('Denying transactions in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in dbm.campaigns:
        logging.info('Campaign is not initialized; aborting.')
        await ctx.send('No campaign exists in this channel.')
        return

    campaign = await dbm.load_campaign(ctx.channel.id, blocking = False)

    terms = ctx.message.content.split(' ', 1)[1].strip()
    denied_indices = await parse_indices(ctx, campaign, terms)

    if denied_indices is None:
        return
    elif not denied_indices:
        logging.info('No accessible transactions; aborting.')
        await ctx.send('Invalid indicies or no pending transactions.')

    campaign = await dbm.load_campaign(ctx.channel.id, blocking = True)

    campaign.deny(denied_indices)

    await dbm.save_campaign(campaign)

    logging.info('Successfully denied transactions.')
    await ctx.send('Transaction(s) denied.')

################################################################################

brief_desc = 'View the account balance of a user'
full_desc = ('Usage: dnd-balance (of [name])\n\n'
             'Show the balance in the account of a player. Only the GM may use '
             'the optional (of [name]) argument. When this argument is not '
             'supplied, the balance of the user calling the command is shown.'
             '\n\nIf the keyword "all" is supplied instead of a player name,'
             'the balances of all registered players is displayed.')

@bot.command(brief = brief_desc, description = full_desc)
async def balance(ctx):
    logging.info('Displaying balance in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in dbm.campaigns:
        logging.info('Campaign is not initialized; aborting.')
        await ctx.send('No campaign exists in this channel.')
        return

    campaign = await dbm.load_campaign(ctx.channel.id)

    arguments = ctx.message.content.split(' ')
    if len(arguments) > 1:
        try:
            if arguments[1] == 'of':
                if ctx.author.id in campaign.gms:
                    target = arguments[2]
                else:
                    logging.info('Unauthorized use of "of"; aborting.')
                    await ctx.send('You are not authorized to use "of".')
                    return
            else:
                raise IndexError('Invalid syntax')
        except IndexError:
            await log_syntax_error(ctx)
            return
    elif ctx.author.id in campaign.players:
        target = campaign.players[ctx.author.id].name
    else:
        logging.info('Unregistered user; aborting.')
        await ctx.send('You are not registered in this campaign.')
        return

    if target == 'all':
        msg = ''
        for id in campaign.players:
            msg += '`' + campaign.players[id].name + ': '
            msg += campaign.players[id].balance + '`\n'
    elif target in campaign.names:
        msg = '`' + campaign.players[campaign.names[target]].balance + '`'
    else:
        logging.info('Invalid participant name; aborting.')
        await ctx.send('No player with name "{0}"'.format(target)
                       + ' exists in this campaign.')
        return

    logging.info('Successfully displayed balance of {0}.'.format(target))
    await ctx.send('Account balance for {0}:\n'.format(target) + msg)

################################################################################

brief_desc = 'Roll dice of the given type and quantity'
full_desc = ('Usage: dnd-roll ([number])d[sides](+[offset])\n\n'
             'Roll [number] [sides]-sided dice with a [offset] roll modifier. '
             'Only the [sides] argument is required, but all values must be '
             'positive integers. For example, "dnd-roll 4d8+3" is valid.')

@bot.command(brief = brief_desc, description = full_desc)
async def roll(ctx):
    logging.info('Rolling dice in #{0}.'.format(ctx.channel.name))

    try:
        intake = ctx.message.content.split(' ')[1]
    except IndexError:
        await log_syntax_error(ctx)
        return

    if len(intake.split('d')) != 2:
        await log_syntax_error()
        return

    rolls = intake.split('d')[0]
    if rolls:
        try:
            rolls = int(rolls)
        except ValueError:
            logging.info('Invalid roll number; aborting.')
            await ctx.send('"{0}" is an invalid number of rolls.'.format(rolls))
            return
    else:
        rolls = 1

    sides = intake.split('d')[1].split('+')[0]
    try:
        sides = int(sides)
    except ValueError:
        logging.info('Invalid roll sides; aborting.')
        await ctx.send('"{0}" is an invalid number of sides.'.format(rolls))
        return

    try:
        offset = int(intake.split('d')[1].split('+')[1])
    except IndexError:
        offset = 0
    except ValueError:
        logging.info('Invalid roll offset; aborting.')
        await ctx.send('"{0}" is an invalid offset.'.format(rolls))
        return

    if rolls <= 100:
        results = [1 + random.randrange(sides) for _ in range(rolls)]
    else:
        try:
            mu = rolls*(sides + 1)/2
            sigma = math.sqrt(rolls*(sides**2 - 1)/12)
        except OverflowError:
            logging.info('Overflow during calculation; aborting')
            await ctx.send('The number of rolls or sides is too large.')
            return
        result = round(random.gauss(mu, sigma))
        result = min(result, rolls*sides)
        result = max(result, rolls)
        results = [result]

    final = sum(results) + offset

    breakdown = ' + '.join(str(result) for result in results)
    breakdown = '||({0}) + {1}||'.format(breakdown, offset)

    msg = 'Rolled {0}: **{1}**\n{2}'.format(intake, final, breakdown)
    if len(msg) >= 2000:
        msg = 'Roll result: {0}'.format(final)
        if len(msg) >= 2000:
            msg = 'Roll result too large to display'

    await ctx.send(msg)

#Commands end
################################################################################
#Events start

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    logging.error('Error in {0}: {1}"'.format(ctx.message.content, error))
    await ctx.send('Error processing command. Use `dnd-help` to view help.')


@bot.event
async def on_ready():
    logging.info('Logged in as {0.name} (ID: {0.id})'.format(bot.user))
    await bot.change_presence(activity = discord.Game(name = status_message))

#Events end
################################################################################
#Initialization start

if __name__ == '__main__':
    token = '' #Manually add token here.
    status_message = 'D&D (dnd-help)'

    if token == '': #Get token if it's not already in the code.
        try:
            file = open('token.txt')
            token = file.read()
            file.close()
            logging.info("Token acquired from file.")
        except FileNotFoundError:
            logging.warning("Token file not found.")
            try:
                token = os.environ['DND_TOKEN']
                logging.info("Token acquired from environment variable.")
            except KeyError:
                logging.warning("Token environment variable not found.")
                logging.error("Token auto detection failed. Aborting.")
                input("Press enter to quit.")
                quit()
    else:
        logging.info("Token acquired from code.")

    dbm = DatabaseManager()
    logging.info('{0} existing campaigns loaded.'.format(len(dbm.campaigns)))

    bot.run(token)
