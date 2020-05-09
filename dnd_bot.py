import logging
import os
import pickle

import discord
from discord.ext import commands

FORMAT = '%(levelname)s:%(name)s:(%(asctime)s): %(message)s'
DATEFMT = '%d-%b-%y %H:%M:%S'
logging.basicConfig(format = FORMAT, datefmt = DATEFMT, level = logging.INFO)

################################################################################
#Initialization start

bot = commands.Bot('dnd-')
token = '' #Manually add token here.
maintenance = False
status_message = 'DnD'

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
            logging.error("Token auto detection failed. Stopping execution.")
            input("Press enter to quit.")
            quit()
else:
    logging.info("Token acquired from code.")

channels = [int(id) for id in os.listdir('data')]

#Initialization end
################################################################################
#Internal classes and functions start

class Campaign:
    def __init__(self, id, gm):
        self.player_names = {}
        self.players = {}
        self.pending = []
        self.archive = []
        self.id = id
        self.gm = gm


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
        return '{0.cp} CP | {0.sp} SP | {0.gp} GP | {0.pp} PP'.format(self)



class Transaction:
    def __init__(self, initiator, mode, amounts, participant, reason):
        self.initiator = initiator
        self.mode = mode
        self.amounts = amounts
        self.participant = participant
        self.reason = reason

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



async def parse_indices(ctx, campaign, terms):
    pending = [transaction for transaction in campaign.pending
               if ctx.author.id in (transaction.participant.id, campaign.gm)]
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
        if ctx.author.id in (transaction.participant.id, campaign.gm):
            if player_index in indices:
                corrected_indices.append(global_index)
            player_index += 1
    corrected_indices.sort()
    return corrected_indices


async def log_syntax_error(ctx):
    logging.info('Invalid syntax; aborting.')
    await ctx.send('Invalid syntax. Ask for help.')


def save_campaign(campaign, id):
    with open('data/{0}'.format(id), 'wb') as file:
        pickle.dump(campaign, file)


def load_campaign(id):
    with open('data/{0}'.format(id), 'rb') as file:
        campaign = pickle.load(file)
    return campaign

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

@bot.command()
async def initialize(ctx):
    logging.info('Initializing new campaign in #{0}.'.format(ctx.channel.name))

    if os.path.isfile('data/{0}'.format(ctx.channel.id)):
        logging.info('Campaign already exists; aborting.')
        await ctx.send('Campaign already exists in this channel.')
        return

    campaign = Campaign(ctx.channel.id, ctx.author.id)
    save_campaign(campaign, ctx.channel.id)
    channels.append(ctx.channel.id)

    logging.info('Initialization successful.')
    await ctx.send('New campaign initialized.')

################################################################################

@bot.command()
async def register(ctx):
    logging.info('Registering new player in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in channels:
        logging.info('Player is already registered; aborting.')
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
            #if not bot.get_user(id):
            #    logging.info('Invalid player ID; aborting.')
            #    await ctx.send('Invalid player ID.')
            #    return
        else:
            raise IndexError('Invalid syntax')
    except IndexError:
        await log_syntax_error(ctx)
        return

    campaign = load_campaign(ctx.channel.id)

    if id in campaign.player_names:
        logging.info('Name already exists in campaign; aborting.')
        await ctx.send('You are already registered as {0}.'.format(name))
        return

    if name in campaign.players:
        logging.info('Name already exists in campaign; aborting.')
        await ctx.send('That name is already taken.')
        return

    campaign.players[name] = Player(id, name)
    campaign.player_names[id] = name
    save_campaign(campaign, ctx.channel.id)

    logging.info('Player "{0}" successfully registered.'.format(name))
    await ctx.send('Successfully registered {0}.'.format(name))

################################################################################

@bot.command()
async def transact(ctx):
    logging.info('Attempting transaction in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in channels:
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

    campaign = load_campaign(ctx.channel.id)

    if 'as' in parsed_args:
        if ctx.author.id == campaign.gm:
            name = parsed_args['as']
            if name in campaign.players:
                initiator = campaign.players[name]
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
        if ctx.author.id in campaign.player_names:
            initiator = campaign.players[campaign.player_names[ctx.author.id]]
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
        if intake in campaign.players:
            participant = campaign.players[intake]
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

    transaction = Transaction(initiator, mode, amounts, participant, reason)
    campaign.pending.append(transaction)

    save_campaign(campaign, ctx.channel.id)

    logging.info('Successfully added transaction to queue.')
    await ctx.send('Transaction recorded; waiting for approval.')

################################################################################

@bot.command()
async def pending(ctx):
    logging.info('Displaying pending in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in channels:
        logging.info('Campaign is not initialized; aborting.')
        await ctx.send('No campaign exists in this channel.')
        return

    campaign = load_campaign(ctx.channel.id)

    msg = ''
    id = 1
    for transaction in campaign.pending:
        if ctx.author.id in (transaction.participant.id, campaign.gm):
            msg += str(id) + ': `' + transaction.text + '`\n'
            id += 1
    msg = msg[ :-1]

    if not msg:
        logging.info('No pending transactions.')
        await ctx.send('There are currently no pending transactions.')
    else:
        logging.info('Transactions successfully displayed.')
        await ctx.send('Pending transactions:\n' + msg)

################################################################################

@bot.command()
async def approve(ctx):
    logging.info('Approving transactions in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in channels:
        logging.info('Campaign is not initialized; aborting.')
        await ctx.send('No campaign exists in this channel.')
        return

    campaign = load_campaign(ctx.channel.id)

    terms = ctx.message.content.split(' ', 1)[1].strip()
    approved_indices = await parse_indices(ctx, campaign, terms)

    if approved_indices is None:
        return
    elif not approved_indices:
        logging.info('No accessible transactions; aborting.')
        await ctx.send('No transactions available for approval.')

    campaign.approve(approved_indices)

    save_campaign(campaign, ctx.channel.id)

    logging.info('Successfully approved transactions.')
    await ctx.send('Transaction(s) successfully approved.')

################################################################################

@bot.command()
async def deny(ctx):
    logging.info('Denying transactions in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in channels:
        logging.info('Campaign is not initialized; aborting.')
        await ctx.send('No campaign exists in this channel.')
        return

    campaign = load_campaign(ctx.channel.id)

    terms = ctx.message.content.split(' ', 1)[1].strip()
    denied_indices = await parse_indices(ctx, campaign, terms)

    if not denied_indices:
        return

    campaign.deny(denied_indices)

    save_campaign(campaign, ctx.channel.id)

    logging.info('Successfully denied transactions.')
    await ctx.send('Transaction(s) denied.')

################################################################################

@bot.command()
async def balance(ctx):
    logging.info('Displaying balance in #{0}.'.format(ctx.channel.name))

    if ctx.channel.id not in channels:
        logging.info('Campaign is not initialized; aborting.')
        await ctx.send('No campaign exists in this channel.')
        return

    campaign = load_campaign(ctx.channel.id)

    arguments = ctx.message.content.split(' ')
    if len(arguments) > 1:
        try:
            if arguments[1] == 'of':
                if ctx.author.id == campaign.gm:
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
    elif ctx.author.id in campaign.player_names:
        target = campaign.player_names[ctx.author.id]
    else:
        logging.info('Unregistered user; aborting.')
        await ctx.send('You are not registered in this campaign.')
        return

    if target in campaign.players:
        msg = campaign.players[target].balance
    else:
        logging.info('Invalid participant name; aborting.')
        await ctx.send('No player with name "{0}"'.format(initiator)
                       + ' exists in this campaign.')
        return

    logging.info('Successfully displayed balance of {0}.'.format(target))
    await ctx.send('Account balance for {0}:\n'.format(target) + msg)

#Commands end
################################################################################

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    try:
        global maintenance #Maintenance mode toggle checking.
        if message.content.split(' ', maxsplit = 1)[1] == 'enable':
            logging.warning('Maintenance mode is enabled.')
            maintenance = True
            msg = 'Maintenance mode'
            await bot.change_presence(activity = discord.Game(name = msg))
            await channel.send('Maintenance mode is enabled.')
            return
        if message.content.split(' ', maxsplit = 1)[1] == 'disable':
            logging.warning('Maintenance mode is disabled.')
            maintenance = False
            msg = status_message
            await bot.change_presence(activity = discord.Game(name = msg))
            await channel.send('Maintenance mode is disabled.')
            return
    except IndexError:
        pass

    if maintenance == True:
        return

    await bot.process_commands(message)

@bot.event
async def on_ready():
    logging.info('Logged in as {0.name} (ID: {0.id})'.format(bot.user))
    await bot.change_presence(activity = discord.Game(name = status_message))

if __name__ == '__main__':
    bot.run(token)
